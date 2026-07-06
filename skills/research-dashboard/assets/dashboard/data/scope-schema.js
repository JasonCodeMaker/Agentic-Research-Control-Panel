"use strict";
// Generated from lib.scope_ssot.scope_schema(); do not hand-edit field rules here.
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
            "minWords": 20
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
      "task": {
        "fields": {
          "config": {
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
          "experiment": {
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
          "experiment",
          "config",
          "gate",
          "control_mode"
        ],
        "primary": [
          "experiment",
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
