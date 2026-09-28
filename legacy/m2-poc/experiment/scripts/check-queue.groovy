import jenkins.model.Jenkins

def q = Jenkins.get().getQueue()
def items = q.getItems()
def computer = Jenkins.get().toComputer()
def busy = computer != null ? computer.countBusy() : 0
def idle = computer != null ? computer.countIdle() : 0

println "QUEUE_LEN:" + items.length
println "BUSY:" + busy
println "IDLE:" + idle
