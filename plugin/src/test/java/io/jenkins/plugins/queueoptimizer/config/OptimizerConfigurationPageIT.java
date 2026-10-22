package io.jenkins.plugins.queueoptimizer.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.util.Secret;
import java.util.List;
import org.htmlunit.html.HtmlCheckBoxInput;
import org.htmlunit.html.HtmlForm;
import org.htmlunit.html.HtmlPage;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * The optimizer's section of Manage Jenkins &gt; System, through the page a user sees (D-072).
 *
 * <p>Milestone 2 had no configuration page (known problem 4), and version 2 had none either until
 * 2026-10-22: its settings could be changed only through Configuration as Code.
 */
@WithJenkins
class OptimizerConfigurationPageIT {

    /** Every setting of report Appendix D, by its field name. */
    private static final List<String> FIELDS = List.of(
            "optimizerEnabled",
            "weightUrgency",
            "weightDependency",
            "weightExecutionTime",
            "agingBonusPerInterval",
            "agingIntervalMinutes",
            "agingCap",
            "estimatorK",
            "similarityThreshold",
            "recencyLambdaPerDay",
            "historyWindow",
            "rescoreIntervalSeconds",
            "metricsEnabled",
            "metricsBackendUrl",
            "metricsToken");

    @Test
    @DisplayName("the System page has a Dynamic Queue Optimizer section with every Appendix D setting")
    void thePageHasEverySetting(JenkinsRule j) throws Exception {
        HtmlPage page = j.createWebClient().goTo("configure");

        assertTrue(page.asNormalizedText().contains("Dynamic Queue Optimizer"));
        HtmlForm form = page.getFormByName("config");
        for (String field : FIELDS) {
            assertFalse(form.getInputsByName("_." + field).isEmpty(), "no input for " + field);
        }
    }

    @Test
    @DisplayName("saving the page unchanged keeps every value, zeros and the token included")
    void savingThePageKeepsEveryValue(JenkinsRule j) throws Exception {
        OptimizerConfiguration config = OptimizerConfiguration.get();
        config.setOptimizerEnabled(false);
        config.setWeightUrgency(0.6);
        config.setWeightDependency(0.25);
        config.setWeightExecutionTime(0.15);
        config.setAgingBonusPerInterval(0.04);
        config.setAgingIntervalMinutes(7);
        config.setAgingCap(0.0); // zero is valid, and the lower boundary
        config.setEstimatorK(3);
        config.setSimilarityThreshold(1.0); // the upper boundary
        config.setRecencyLambdaPerDay(0.0);
        config.setHistoryWindow(20);
        config.setRescoreIntervalSeconds(30);
        config.setMetricsEnabled(false);
        config.setMetricsBackendUrl("http://backend.example:8000/api/metrics");
        config.setMetricsToken(Secret.fromString("a-metrics-token"));

        j.configRoundtrip();

        assertFalse(config.isOptimizerEnabled());
        assertEquals(0.6, config.getWeightUrgency());
        assertEquals(0.25, config.getWeightDependency());
        assertEquals(0.15, config.getWeightExecutionTime());
        assertEquals(0.04, config.getAgingBonusPerInterval());
        assertEquals(7, config.getAgingIntervalMinutes());
        assertEquals(0.0, config.getAgingCap());
        assertEquals(3, config.getEstimatorK());
        assertEquals(1.0, config.getSimilarityThreshold());
        assertEquals(0.0, config.getRecencyLambdaPerDay());
        assertEquals(20, config.getHistoryWindow());
        assertEquals(30, config.getRescoreIntervalSeconds());
        assertFalse(config.isMetricsEnabled());
        assertEquals("http://backend.example:8000/api/metrics", config.getMetricsBackendUrl());
        assertEquals("a-metrics-token", Secret.toString(config.getMetricsToken()));
    }

    @Test
    @DisplayName("a value typed on the page is saved")
    void aValueTypedOnThePageIsSaved(JenkinsRule j) throws Exception {
        HtmlForm form = j.createWebClient().goTo("configure").getFormByName("config");
        form.getInputByName("_.agingIntervalMinutes").setValue("10");
        form.getInputByName("_.weightUrgency").setValue("0.45");
        ((HtmlCheckBoxInput) form.getInputByName("_.optimizerEnabled")).setChecked(false);

        j.submit(form);

        OptimizerConfiguration config = OptimizerConfiguration.get();
        assertEquals(10, config.getAgingIntervalMinutes());
        assertEquals(0.45, config.getWeightUrgency());
        assertFalse(config.isOptimizerEnabled());
    }

    @Test
    @DisplayName("the page's weight check is sent the other two weights and warns about their sum")
    void theWeightCheckReadsTheOtherTwoFields(JenkinsRule j) throws Exception {
        // The parameter names must be the form's field names, or the page would send nothing for
        // them and the warning would be computed on zeros.
        String check = "descriptorByName/" + OptimizerConfiguration.class.getName() + "/checkWeightUrgency"
                + "?value=0.6&weightDependency=0.3&weightExecutionTime=0.2";

        String answer = j.createWebClient().goTo(check, null).getWebResponse().getContentAsString();

        assertTrue(answer.contains("1.100"), answer);
    }
}
