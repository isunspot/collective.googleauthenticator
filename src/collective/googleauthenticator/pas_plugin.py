"""
The idea of this PAS plugin is quite simple. It should check the user profile
for the user being logged in and if user has enabled two-step verification for
his account (``enable_two_factor_authentication`` is set to True), then
redirect him further to a another page, where he would enter his Google
Authenticator token, after successful validation of which the user would be
definitely logged in.

If user has not enabled the two-step verification for his account
(``enable_two_factor_authentication`` is set to False), then do nothing so
that Plone continues logging in the user normal way.
"""
import logging

from Globals import InitializeClass
from AccessControl.SecurityInfo import ClassSecurityInfo

from plone import api

from Products.PluggableAuthService.PluggableAuthService import reraise
from Products.PluggableAuthService.PluggableAuthService import _SWALLOWABLE_PLUGIN_EXCEPTIONS
from Products.PluggableAuthService.plugins.BasePlugin import BasePlugin
from Products.PluggableAuthService.utils import classImplements
from Products.PluggableAuthService.interfaces.plugins import IAuthenticationPlugin
from Products.PageTemplates.PageTemplateFile import PageTemplateFile

from collective.googleauthenticator.adapter import ICameFrom
from collective.googleauthenticator.helpers import is_whitelisted_client
from collective.googleauthenticator.helpers import sign_user_data


logger = logging.getLogger("collective.googleauthenticator")

manage_addGoogleAuthenticatorPluginForm = PageTemplateFile(
    './www/add_google_authenticator_form',
    globals(),
    __name__='manage_addGoogleAuthenticatorPluginForm'
)


def addGoogleAuthenticatorPlugin(self, id, title='', REQUEST=None):
    """
    Add a Google Authenticator PAS Plugin to Plone PAS
    """
    o = GoogleAuthenticatorPlugin(id, title)
    self._setObject(o.getId(), o)

    if REQUEST is not None:
        msg = 'Google+Authentiactor+PAS+Plugin+added.'
        REQUEST['RESPONSE'].redirect(
            '{0}/manage_main?manage_tabs_message={1}'.format(
                self.absolute_url(), msg))


class GoogleAuthenticatorPlugin(BasePlugin):
    """
    Google Authenticator PAS Plugin
    """
    meta_type = 'Collective Google Authenticator PAS'
    security = ClassSecurityInfo()

    def __init__(self, id, title=None):
        self._setId(id)
        self.title = title

    def authenticateCredentials(self, credentials):
        """
        Place to actually validate the user credentials specified and return a
        tuple (login, login) on success or (None, None) on failure.

        If we find one and two-step verification is not enabled for the
        account, we consider the authentication passed and log the user in. If
        two-step verification has been enabled for the account, the first step
        of authentication is considered to be passed and we go to the next
        page (having the user and pass remembered), where we check for the
        token generated by the token generator (Google Authenticator). If the
        token is valid too, we log the user in.
        """

        if is_whitelisted_client():
            return None

        login = credentials['login']

        if not login:
            return None

        user = api.user.get(username=login)

        logger.debug("Found user: {0}".format(user.getProperty('username')))

        two_factor_authentication_enabled = user.getProperty(
            'enable_two_factor_authentication')
        logger.debug("Two-step verification enabled: {0}".format(
            two_factor_authentication_enabled))

        if two_factor_authentication_enabled:
            # First see, if the password is correct.
            # We do this by allowing all IAuthenticationPlugin plugins to
            # authenticate the credentials, and pick the first one that is
            # successful.
            pas_plugins = self._getPAS().plugins
            auth_plugins = pas_plugins.listPlugins(IAuthenticationPlugin)
            authorized = None
            for plugid, authplugin in auth_plugins:
                if plugid == self.getId():
                    # Avoid infinite recursion
                    continue

                try:
                    authorized = authplugin.authenticateCredentials(
                        credentials)
                except _SWALLOWABLE_PLUGIN_EXCEPTIONS:
                    reraise(authplugin)
                    msg = 'AuthenticationPlugin {0} error'.format(plugid)
                    logger.info(msg, exc_info=True)
                    continue

                if authorized is not None:
                    # An auth plugin successfully authenticated the user
                    break

            if authorized is None:
                # No auth plugin was able to authenticate the user
                return None

            # Consume the credentials after we verified the credentials above.
            # We need to do this to prevent later IAuthenticationPlugins
            # from authenticating the user before we verified the token.
            # This does produce a "Login failed" status message though that
            # we need to remove in the token validation view
            for key in credentials.keys():
                del credentials[key]

            # Setting the data in the session doesn't seem to work. That's why
            # we use the `ska` package.
            # The secret key would be then a combination of username, secret
            # stored in users' profile and the browser version.
            request = self.REQUEST
            response = request['RESPONSE']
            response.setCookie('__ac', '', path='/')

            # Redirect to token thing...
            signed_url = sign_user_data(request=request, user=user,
                                        url='@@google-authenticator-token')

            came_from_adapter = ICameFrom(request)
            # Appending possible `came_from`, but give it another name.
            came_from = came_from_adapter.getCameFrom()
            if came_from:
                signed_url = '{0}&next_url={1}'.format(signed_url, came_from)

            response.redirect(signed_url, lock=1)

            return None

        if credentials.get('extractor') != self.getId():
            return None

        return None


classImplements(GoogleAuthenticatorPlugin, IAuthenticationPlugin)
InitializeClass(GoogleAuthenticatorPlugin)
