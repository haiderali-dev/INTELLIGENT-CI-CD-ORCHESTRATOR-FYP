import jenkins.model.*
import hudson.security.*

def instance = Jenkins.get()

instance.setSecurityRealm(SecurityRealm.NO_AUTHENTICATION)
instance.setAuthorizationStrategy(AuthorizationStrategy.UNSECURED)

instance.setNumExecutors(1)

instance.save()
