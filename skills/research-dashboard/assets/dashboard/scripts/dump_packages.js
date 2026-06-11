#!/usr/bin/env node
// Dumps the dashboard data files as one JSON document on stdout so the
// Python tooling (learnings_lint.py) can consume them without re-parsing JS.

const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');

global.window = {};
global.document = { addEventListener: () => {} };

eval(fs.readFileSync(path.join(root, 'data/schema.js'), 'utf8'));
eval(fs.readFileSync(path.join(root, 'data/research-packages.js'), 'utf8'));
const rulesJs = path.join(root, 'data/rules.js');
if (fs.existsSync(rulesJs)) eval(fs.readFileSync(rulesJs, 'utf8'));

process.stdout.write(JSON.stringify({
  schema: window.RESEARCH_STATUS_SCHEMA,
  statusFamily: window.RESEARCH_STATUS_FAMILY,
  contributionSpine: window.RESEARCH_CONTRIBUTION_SPINE,
  methodsTriedFields: window.RESEARCH_METHODS_TRIED_FIELDS,
  categories: window.RESEARCH_CATEGORIES,
  packages: window.RESEARCH_PACKAGES,
  rules: window.RESEARCH_RULES || [],
}, null, 2));
