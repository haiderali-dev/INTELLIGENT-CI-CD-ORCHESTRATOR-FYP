package io.jenkins.plugins.queueoptimizer.property;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Proves that a Milestone 2 job configuration still loads after the property field was renamed
 * from {@code priority} to {@code level}.
 *
 * <p>BUILD_PROMPT 4.3.2 asks for two things that cannot both hold: the field must be
 * {@code level}, because that is the syntax the report's Appendix D and the specification both
 * publish for {@code @Symbol}, and Milestone 2's field names must keep working. Milestone 2's
 * field is {@code priority}.
 *
 * <p>The resolution is to satisfy the requirement by mechanism rather than by name: the data-bound
 * field is {@code level}, and {@code readResolve} folds a stored {@code <priority>} element onto
 * it. This test is what makes that claim checkable rather than assumed. See
 * {@code docs/decisions.md} D-005.
 *
 * <p>The XML below is the real shape Milestone 2 wrote, taken from
 * {@code legacy/m2-poc/.../JobPriorityProperty.java} and its {@code config.jelly}.
 */
@WithJenkins
class Milestone2CompatibilityIT {

    private static final String M2_CONFIG_XML = """
            <?xml version='1.1' encoding='UTF-8'?>
            <project>
              <description>A job configured under Milestone 2</description>
              <keepDependencies>false</keepDependencies>
              <properties>
                <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>
                  <priority>HIGH</priority>
                  <dependsOn>build-api, run-unit-tests</dependsOn>
                </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>
              </properties>
              <scm class="hudson.scm.NullSCM"/>
              <canRoam>true</canRoam>
              <disabled>false</disabled>
              <triggers/>
              <builders/>
              <publishers/>
              <buildWrappers/>
            </project>
            """;

    @Test
    @DisplayName("a Milestone 2 config.xml keeps its HIGH priority and its dependencies")
    void milestone2ConfigStillLoads(JenkinsRule j) throws Exception {
        FreeStyleProject project = (FreeStyleProject) j.jenkins.createProjectFromXML(
                "m2-job", new ByteArrayInputStream(M2_CONFIG_XML.getBytes(StandardCharsets.UTF_8)));

        JobPriorityProperty property = project.getProperty(JobPriorityProperty.class);

        assertNotNull(property, "the Milestone 2 property element did not deserialize at all");
        assertEquals(
                PriorityLevel.HIGH,
                property.getPriorityLevel(),
                "a HIGH job silently becoming MEDIUM is the worst possible outcome of this rename: "
                        + "it downgrades urgent work with no error anywhere");
        assertEquals("HIGH", property.getLevel());
        assertEquals(List.of("build-api", "run-unit-tests"), property.getDependsOnList());
    }

    @Test
    @DisplayName("a reloaded Milestone 2 job round-trips through the new field name")
    void reloadedJobRoundTripsToTheNewField(JenkinsRule j) throws Exception {
        j.jenkins.createProjectFromXML(
                "m2-roundtrip", new ByteArrayInputStream(M2_CONFIG_XML.getBytes(StandardCharsets.UTF_8)));

        // Saving rewrites config.xml through the current field names.
        FreeStyleProject project = j.jenkins.getItemByFullName("m2-roundtrip", FreeStyleProject.class);
        assertNotNull(project);
        project.save();

        String rewritten = project.getConfigFile().asString();
        assertTrue(
                rewritten.contains("<level>HIGH</level>"),
                "after a save the property should be stored under the new field name:\n" + rewritten);

        // And the reloaded job still reads HIGH.
        j.jenkins.reload();
        FreeStyleProject reloaded = j.jenkins.getItemByFullName("m2-roundtrip", FreeStyleProject.class);
        assertNotNull(reloaded);
        assertEquals(
                PriorityLevel.HIGH,
                reloaded.getProperty(JobPriorityProperty.class).getPriorityLevel());
    }

    @Test
    @DisplayName("a config.xml already using the new field name loads unchanged")
    void newFieldNameLoads(JenkinsRule j) throws Exception {
        String xml = M2_CONFIG_XML.replace("<priority>HIGH</priority>", "<level>LOW</level>");

        FreeStyleProject project = (FreeStyleProject) j.jenkins.createProjectFromXML(
                "v2-job", new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8)));

        assertEquals(
                PriorityLevel.LOW,
                project.getProperty(JobPriorityProperty.class).getPriorityLevel());
    }

    @Test
    @DisplayName("a job with no priority property at all defaults to MEDIUM")
    void missingPropertyDefaultsToMedium(JenkinsRule j) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject("no-property");

        assertEquals(
                PriorityLevel.MEDIUM,
                JobPriorityProperty.levelOf(project),
                "an unconfigured job must be schedulable, not rejected");
    }
}
