package io.jenkins.plugins.queueoptimizer.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.jenkins.plugins.casc.ConfigurationContext;
import io.jenkins.plugins.casc.ConfiguratorRegistry;
import io.jenkins.plugins.casc.misc.ConfiguredWithCode;
import io.jenkins.plugins.casc.misc.JenkinsConfiguredWithCodeRule;
import io.jenkins.plugins.casc.misc.junit.jupiter.WithJenkinsConfiguredWithCode;
import io.jenkins.plugins.casc.model.CNode;
import io.jenkins.plugins.casc.model.Mapping;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Required by BUILD_PROMPT 4.3.10: the configuration round-trips through YAML export.
 *
 * <p>Configuration as Code is not a convenience here, it is what makes the experiment reproducible.
 * The baseline and optimized arms differ only by {@code optimizerEnabled}, and both are described by
 * a checked-in YAML file, so a run can be reconstructed from the repository rather than from
 * somebody's memory of which checkboxes were ticked. Milestone 2 configured two Jenkins homes by
 * hand, which is why its two arms were not otherwise comparable.
 *
 * <p><b>Floating-point values must be quoted in YAML.</b> On
 * {@code configuration-as-code:2121.v86fe99d4b_b_a_b_}, JCasC's YAML model only builds nodes for
 * YAML's {@code bool}, {@code int} and {@code str} tags, so an unquoted {@code 0.6} (tag
 * {@code float}) is dropped from the parsed document without a warning. Quoted, it is a string,
 * which JCasC converts to {@code double} like any other scalar. See
 * {@link #quotedFloatingPointValuesApply}, {@link #unquotedFloatingPointValuesAreDroppedByJCasC} and
 * {@code docs/decisions.md} D-017.
 */
@WithJenkinsConfiguredWithCode
class ConfigAsCodeIT {

    @Test
    @DisplayName("YAML sets the integer, boolean, string and secret fields")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void yamlSetsNonFloatingPointFields(JenkinsConfiguredWithCodeRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();

        // optimizerEnabled is the field the experiment actually switches between its two arms, and
        // it applies correctly. That is what keeps the main comparison reproducible from YAML.
        assertFalse(config.isOptimizerEnabled(), "the baseline arm turns the optimizer off");

        assertEquals(3, config.getAgingIntervalMinutes());
        assertEquals(7, config.getEstimatorK());
        assertEquals(25, config.getHistoryWindow());
        assertEquals(30, config.getRescoreIntervalSeconds());
        assertTrue(config.isMetricsEnabled());
        assertEquals("http://backend:8000/api/metrics", config.getMetricsBackendUrl());
    }

    @Test
    @DisplayName("the metrics token is read from YAML and stored as a Secret")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void tokenIsStoredAsASecret(JenkinsConfiguredWithCodeRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertNotNull(config.getMetricsToken(), "the token should have been read from the YAML");
        assertEquals("s3cr3t-metrics-token", config.getMetricsToken().getPlainText());
        assertTrue(config.isMetricsPublishable(), "a URL and a token together mean publishable");
    }

    @Test
    @DisplayName("quoted floating-point values apply, so the aging ablation can be driven from YAML")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void quotedFloatingPointValuesApply(JenkinsConfiguredWithCodeRule j) {
        // The YAML quotes every one: weightUrgency "0.6", weightDependency "0.25",
        // weightExecutionTime "0.15", agingBonusPerInterval "0.08", agingCap "0.24",
        // similarityThreshold "0.4" and recencyLambdaPerDay "0.2". None is an Appendix D default.
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertEquals(0.6, config.getWeightUrgency(), 1e-9);
        assertEquals(0.25, config.getWeightDependency(), 1e-9);
        assertEquals(0.15, config.getWeightExecutionTime(), 1e-9);
        assertEquals(0.08, config.getAgingBonusPerInterval(), 1e-9);
        assertEquals(0.24, config.getAgingCap(), 1e-9);
        assertEquals(0.4, config.getSimilarityThreshold(), 1e-9);
        assertEquals(0.2, config.getRecencyLambdaPerDay(), 1e-9);
    }

    @Test
    @DisplayName("JCASC BEHAVIOUR: unquoted floating-point values are dropped without a warning")
    @ConfiguredWithCode("optimizer-unquoted-floats.yaml")
    void unquotedFloatingPointValuesAreDroppedByJCasC(JenkinsConfiguredWithCodeRule j) {
        // Pins JCasC's behaviour, not ours, so the quoting rule has a reason anyone can run. The
        // file writes 0.6, 0.08 and 0.24 unquoted: each is dropped and its default stays, while the
        // integer beside them applies. verify.py refuses an unquoted float in jenkins/casc/. If a
        // later JCasC reads them, this fails, and the rule can go.
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertEquals(7, config.getEstimatorK(), "the integer in the same block applies");
        assertEquals(0.5, config.getWeightUrgency(), 1e-9, "0.6 unquoted was dropped");
        assertEquals(0.05, config.getAgingBonusPerInterval(), 1e-9, "0.08 unquoted was dropped");
        assertEquals(0.15, config.getAgingCap(), 1e-9, "0.24 unquoted was dropped");
    }

    @Test
    @DisplayName("every field survives an export, including the floating-point ones")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void everyFieldSurvivesExport(JenkinsConfiguredWithCodeRule j) throws Exception {
        // The round trip: every field the YAML set comes back out, with the value it set.
        ConfiguratorRegistry registry = ConfiguratorRegistry.get();
        ConfigurationContext context = new ConfigurationContext(registry);
        CNode exported =
                registry.lookupOrFail(OptimizerConfiguration.class).describe(OptimizerConfiguration.get(), context);

        assertNotNull(exported, "the configuration exported to nothing at all");
        Mapping mapping = exported.asMapping();

        for (String field : new String[] {
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
            "metricsBackendUrl"
        }) {
            assertTrue(mapping.containsKey(field), "export dropped the field '" + field + "'");
        }

        assertEquals("false", mapping.get("optimizerEnabled").toString());
        assertEquals("7", mapping.get("estimatorK").toString());
        assertEquals("0.6", mapping.get("weightUrgency").toString());
        assertEquals("0.08", mapping.get("agingBonusPerInterval").toString());
        assertEquals("0.24", mapping.get("agingCap").toString());
        assertEquals(
                "http://backend:8000/api/metrics",
                mapping.get("metricsBackendUrl").toString());
    }

    @Test
    @DisplayName("an exported file imports again with its floating-point values")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void anExportedFileImportsAgainWithItsFloatingPointValues(JenkinsConfiguredWithCodeRule j) throws Exception {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        io.jenkins.plugins.casc.ConfigurationAsCode.get().export(out);
        String yaml = out.toString(java.nio.charset.StandardCharsets.UTF_8);

        OptimizerConfiguration config = OptimizerConfiguration.get();
        config.setWeightUrgency(0.5);
        config.setAgingBonusPerInterval(0.05);
        config.setAgingCap(0.15);
        io.jenkins.plugins.casc.ConfigurationAsCode.get()
                .configureWith(io.jenkins.plugins.casc.yaml.YamlSource.of(
                        new java.io.ByteArrayInputStream(yaml.getBytes(java.nio.charset.StandardCharsets.UTF_8))));

        assertEquals(0.6, config.getWeightUrgency(), 1e-9, "the export wrote: " + optimizerLines(yaml));
        assertEquals(0.08, config.getAgingBonusPerInterval(), 1e-9);
        assertEquals(0.24, config.getAgingCap(), 1e-9);
    }

    private static String optimizerLines(String yaml) {
        return yaml.lines()
                .filter(line -> line.contains("weightUrgency") || line.contains("agingCap"))
                .map(String::strip)
                .collect(java.util.stream.Collectors.joining(", "));
    }

    @Test
    @DisplayName("an exported secret is not the plain text")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void exportedSecretIsEncrypted(JenkinsConfiguredWithCodeRule j) throws Exception {
        ConfiguratorRegistry registry = ConfiguratorRegistry.get();
        ConfigurationContext context = new ConfigurationContext(registry);
        CNode exported =
                registry.lookupOrFail(OptimizerConfiguration.class).describe(OptimizerConfiguration.get(), context);

        Mapping mapping = exported.asMapping();
        if (mapping.containsKey("metricsToken")) {
            assertFalse(
                    mapping.get("metricsToken").toString().contains("s3cr3t-metrics-token"),
                    "an exported YAML is a file people commit; the plain-text token must not be in it");
        }
    }

    @Test
    @DisplayName("omitted fields keep their Appendix D defaults")
    @ConfiguredWithCode("optimizer-minimal.yaml")
    void omittedFieldsKeepTheirDefaults(JenkinsConfiguredWithCodeRule j) {
        // The shape the experiment's two arms use: they differ by one line, and everything else
        // must stay at the report's values rather than being zeroed.
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertFalse(config.isOptimizerEnabled(), "the one field the file sets");
        assertEquals(0.5, config.getWeightUrgency(), 0.0001);
        assertEquals(0.3, config.getWeightDependency(), 0.0001);
        assertEquals(0.2, config.getWeightExecutionTime(), 0.0001);
        assertEquals(5, config.getAgingIntervalMinutes());
        assertEquals(5, config.getEstimatorK());
        assertEquals(50, config.getHistoryWindow());
        assertTrue(config.weightsSumToOne(), "the defaults must still be the report's formula");
        assertEquals("", config.getMetricsBackendUrl(), "empty by default, per D-006");
    }

    @Test
    @DisplayName("the experiment's baseline arm is reproducible from YAML")
    @ConfiguredWithCode("optimizer-minimal.yaml")
    void baselineArmIsReproducibleFromYaml(JenkinsConfiguredWithCodeRule j) {
        // The property that actually matters for the experiment, stated as its own test so the
        // known defect above cannot be mistaken for "JCasC does not work here at all".
        assertFalse(
                OptimizerConfiguration.get().isOptimizerEnabled(),
                "the baseline arm must be configurable from a checked-in file, or the experiment "
                        + "is not reproducible");
    }
}
