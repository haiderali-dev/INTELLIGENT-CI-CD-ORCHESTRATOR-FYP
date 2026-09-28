import io.jenkins.plugins.queueoptimizer.dispatcher.DynamicQueueDispatcher
import groovy.json.JsonOutput

def heap = DynamicQueueDispatcher.getHeap()
def ordered = heap.getAllOrdered()

def out = ordered.collect { sj ->
    [
        jobName         : sj.getJobName(),
        score           : sj.getPriorityScore(),
        estimatedSeconds: sj.getEstimatedDurationSeconds(),
        hasDependency   : sj.hasDependency()
    ]
}

println JsonOutput.toJson(out)
