package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static org.junit.jupiter.api.Assertions.assertEquals;

import hudson.maven.MavenModuleSet;
import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Maven jobs are ranked by the same formula as freestyle ones (`BUILD_PROMPT.md` Part 2.3, "job
 * types: freestyle, Maven and Pipeline"; T2.4).
 *
 * <p>Nothing tested this until 2026-10-22: `JobResolver` said Maven jobs "only ever take branch
 * one", and no test had queued one. The builds fail at once, since no Maven installation is
 * configured, but dispatch order is decided before a build starts, and that is what is asserted.
 * A Maven job's whole-project build is one queue item, the job itself; modules built in parallel,
 * which Maven jobs do only when told to, are not covered.
 */
@WithJenkins
class MavenPriorityIT {

    @Test
    @DisplayName("a HIGH Maven job runs before a MEDIUM freestyle job, and that before a LOW Maven job")
    void mavenJobsAreRankedWithTheRest(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        // Submitted LOW, MEDIUM, HIGH, so arrival order and priority order disagree throughout.
        maven(j, "mvn-low", "LOW").scheduleBuild2(0);
        FreeStyleProject medium = j.createFreeStyleProject("fs-medium");
        medium.addProperty(new JobPriorityProperty("MEDIUM", ""));
        medium.scheduleBuild2(0);
        maven(j, "mvn-high", "HIGH").scheduleBuild2(0);
        waitUntilBuildable(j, 3);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("mvn-low", "fs-medium", "mvn-high"));

        assertEquals(
                List.of("mvn-high", "fs-medium", "mvn-low"),
                dispatches.order(),
                "one executor fixes the whole order, so a Maven job ranked by arrival would show here");
    }

    private static MavenModuleSet maven(JenkinsRule j, String name, String level) throws Exception {
        MavenModuleSet job = j.jenkins.createProject(MavenModuleSet.class, name);
        job.addProperty(new JobPriorityProperty(level, ""));
        return job;
    }
}
