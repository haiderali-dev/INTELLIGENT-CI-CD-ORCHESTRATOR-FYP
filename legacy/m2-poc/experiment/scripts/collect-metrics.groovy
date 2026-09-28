import jenkins.model.Jenkins
import hudson.model.FreeStyleProject
import groovy.json.JsonOutput

def results = []

Jenkins.get().getAllItems(FreeStyleProject.class).each { job ->
    def lastBuild = job.getLastBuild()
    def entry = [
        name     : job.getName(),
        result   : lastBuild?.getResult()?.toString(),
        startTime: lastBuild?.getStartTimeInMillis(),
        duration : lastBuild?.getDuration(),
        number   : lastBuild?.getNumber()
    ]

    // Read JobPriorityProperty via reflection so this script works on the
    // baseline instance too, where the plugin class does not exist.
    try {
        def propClass = Jenkins.get().getPluginManager().uberClassLoader
                .loadClass("io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty")
        def prop = job.getProperty(propClass)
        if (prop != null) {
            entry.priority  = prop.getPriority()
            entry.dependsOn = prop.getDependsOn()
        }
    } catch (ClassNotFoundException ignored) {
        // plugin not installed on this instance
    }

    results << entry
}

println JsonOutput.toJson(results)
