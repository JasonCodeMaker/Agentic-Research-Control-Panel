"use strict";
// Generated from lib/research_state/schema.json; do not hand-edit field rules.
(function (root) {
  root.SCOPE_SCHEMA = {
    "levels": {
      "direction": {
        "fields": {
          "baselines": {
            "kind": "list",
            "label": "Baselines",
            "maxWords": 50,
            "minWords": 5
          },
          "hypothesis": {
            "kind": "text",
            "label": "Hypothesis",
            "maxWords": 100,
            "minWords": 20
          },
          "metric": {
            "kind": "metric",
            "label": "Metric",
            "maxWords": 100,
            "minWords": 20
          },
          "success_gate": {
            "kind": "text",
            "label": "Success gate",
            "maxWords": 100,
            "minWords": 20
          }
        },
        "order": [
          "hypothesis",
          "metric",
          "baselines",
          "success_gate"
        ],
        "primary": [
          "hypothesis",
          "metric"
        ]
      },
      "project": {
        "fields": {
          "contributions": {
            "kind": "list",
            "label": "Contributions",
            "maxWords": 50,
            "minWords": 5
          },
          "goal": {
            "kind": "text",
            "label": "Goal",
            "maxWords": 100,
            "minWords": 3
          },
          "out_of_scope": {
            "kind": "list",
            "label": "Out of scope",
            "maxWords": 50,
            "minWords": 5
          }
        },
        "order": [
          "goal",
          "contributions",
          "out_of_scope"
        ],
        "primary": [
          "goal"
        ]
      },
      "experiment": {
        "fields": {
          "config_ref": {
            "kind": "ref",
            "label": "Config"
          },
          "control_mode": {
            "kind": "enum",
            "label": "Control mode",
            "values": [
              "AUTONOMOUS",
              "CHECKPOINTED",
              "DEFERRED",
              "SUPERVISED"
            ]
          },
          "purpose": {
            "kind": "text",
            "label": "Experiment",
            "maxWords": 100,
            "minWords": 20
          },
          "gate": {
            "kind": "text",
            "label": "Gate",
            "maxWords": 100,
            "minWords": 20
          }
        },
        "order": [
          "purpose",
          "config_ref",
          "gate",
          "control_mode"
        ],
        "primary": [
          "purpose",
          "control_mode"
        ]
      }
    },
    "oldNodeFields": [
      "yardstick",
      "provenance"
    ],
    "readingFields": [
      "current_best",
      "measured",
      "methodsTried",
      "metric_value",
      "primaryMetricVsGate",
      "result",
      "verdict"
    ]
  };
})(typeof window !== "undefined" ? window : globalThis);
