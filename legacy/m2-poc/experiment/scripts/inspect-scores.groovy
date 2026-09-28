import io.jenkins.plugins.queueoptimizer.dispatcher.DynamicQueueDispatcher

def heap = DynamicQueueDispatcher.getHeap()
def ordered = heap.getAllOrdered()

if (ordered.isEmpty()) {
    println "(heap is empty - no buildable items waiting right now)"
} else {
    ordered.eachWithIndex { sj, idx ->
        println String.format("%2d. score=%6.2f  %s", idx + 1, sj.getPriorityScore(), sj.getJobName())
    }
}
