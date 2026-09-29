package io.jenkins.plugins.queueoptimizer.property;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.List;
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition;
import org.jenkinsci.plugins.workflow.job.WorkflowJob;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Required by BUILD_PROMPT 4.3.10: the {@code options} and {@code properties} forms both set the
 * property.
 *
 * <p>Both are published, so both have to work: report Appendix D documents the scripted
 * {@code properties([...])} form, and BUILD_PROMPT 4.3.2 additionally documents the declarative
 * {@code options { ... }} form. They are what makes {@code @Symbol("dynamicQueuePriority")} worth
 * having, and they are also why the field had to be renamed from Milestone 2's {@code priority} to
 * {@code level} — the Groovy parameter name comes from the data-bound constructor. See
 * {@code docs/decisions.md} D-005.
 *
 * <p>One caveat the tests below make concrete: a property declared inside a Jenkinsfile only exists
 * after that build has run, because the script has to execute before Jenkins knows about it. The
 * first build of such a job is therefore scheduled at the default priority. That is exactly why the
 * backend also writes the property into {@code config.xml} at creation time rather than relying on
 * the Jenkinsfile alone.
 */
@WithJenkins
class DeclarativeOptionsIT {

    @Test
    @DisplayName("the scripted properties([...]) form sets level and dependsOn")
    void scriptedPropertiesForm(JenkinsRule j) throws Exception {
        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "scripted-form");
        job.setDefinition(new CpsFlowDefinition("""
                properties([
                    dynamicQueuePriority(level: 'HIGH', dependsOn: 'build-api')
                ])
                node { echo 'done' }
                """, true));

        j.buildAndAssertSuccess(job);

        JobPriorityProperty property = job.getProperty(JobPriorityProperty.class);
        assertNotNull(property, "the properties step did not register the job property");
        assertEquals(PriorityLevel.HIGH, property.getPriorityLevel());
        assertEquals(List.of("build-api"), property.getDependsOnList());
    }

    @Test
    @DisplayName("the declarative options { } form sets level and dependsOn")
    void declarativeOptionsForm(JenkinsRule j) throws Exception {
        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "declarative-form");
        job.setDefinition(new CpsFlowDefinition("""
                pipeline {
                    agent any
                    options {
                        dynamicQueuePriority(level: 'LOW', dependsOn: 'build-api')
                    }
                    stages {
                        stage('Build') {
                            steps { echo 'done' }
                        }
                    }
                }
                """, true));

        j.buildAndAssertSuccess(job);

        JobPriorityProperty property = job.getProperty(JobPriorityProperty.class);
        assertNotNull(property, "the declarative options block did not register the job property");
        assertEquals(PriorityLevel.LOW, property.getPriorityLevel());
        assertEquals(List.of("build-api"), property.getDependsOnList());
    }

    @Test
    @DisplayName("the level alone is enough; dependsOn is optional")
    void levelOnly(JenkinsRule j) throws Exception {
        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "level-only");
        job.setDefinition(new CpsFlowDefinition("""
                pipeline {
                    agent any
                    options { dynamicQueuePriority(level: 'HIGH') }
                    stages {
                        stage('Build') { steps { echo 'done' } }
                    }
                }
                """, true));

        j.buildAndAssertSuccess(job);

        JobPriorityProperty property = job.getProperty(JobPriorityProperty.class);
        assertNotNull(property);
        assertEquals(PriorityLevel.HIGH, property.getPriorityLevel());
        assertTrue(property.getDependsOnList().isEmpty());
    }

    @Test
    @DisplayName("a Jenkinsfile property takes effect only after the first build")
    void propertyAppearsOnlyAfterTheFirstRun(JenkinsRule j) throws Exception {
        // The caveat the backend has to work around, asserted rather than assumed. Before the
        // first build the script has not executed, so Jenkins knows nothing about the declared
        // priority and the job is scheduled as MEDIUM.
        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "deferred-property");
        job.setDefinition(new CpsFlowDefinition("""
                pipeline {
                    agent any
                    options { dynamicQueuePriority(level: 'HIGH') }
                    stages {
                        stage('Build') { steps { echo 'done' } }
                    }
                }
                """, true));

        assertEquals(
                PriorityLevel.MEDIUM,
                JobPriorityProperty.levelOf(job),
                "before the first run the declared HIGH is not yet visible, which is why the "
                        + "backend writes the property into config.xml at creation time");

        j.buildAndAssertSuccess(job);

        assertEquals(
                PriorityLevel.HIGH,
                JobPriorityProperty.levelOf(job),
                "after the run the declared level should be in force");
    }

    @Test
    @DisplayName("an invalid level in a Jenkinsfile degrades to MEDIUM rather than failing the build")
    void invalidLevelDegrades(JenkinsRule j) throws Exception {
        // A scheduling hint must never be able to fail someone's build.
        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "bad-level");
        job.setDefinition(new CpsFlowDefinition("""
                pipeline {
                    agent any
                    options { dynamicQueuePriority(level: 'URGENT') }
                    stages {
                        stage('Build') { steps { echo 'done' } }
                    }
                }
                """, true));

        j.buildAndAssertSuccess(job);

        assertEquals(PriorityLevel.MEDIUM, JobPriorityProperty.levelOf(job));
    }

    @Test
    @DisplayName("re-declaring the level on a later build replaces the earlier one")
    void redeclaringReplaces(JenkinsRule j) throws Exception {
        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "changing-level");
        job.setDefinition(
                new CpsFlowDefinition("properties([dynamicQueuePriority(level: 'LOW')])\nnode { echo 'a' }", true));
        j.buildAndAssertSuccess(job);
        assertEquals(PriorityLevel.LOW, JobPriorityProperty.levelOf(job));

        job.setDefinition(
                new CpsFlowDefinition("properties([dynamicQueuePriority(level: 'HIGH')])\nnode { echo 'b' }", true));
        j.buildAndAssertSuccess(job);

        assertEquals(
                PriorityLevel.HIGH,
                JobPriorityProperty.levelOf(job),
                "an edited Jenkinsfile must update the priority, not accumulate two of them");
    }
}
