# Analysis visualization layout reference

These snippets document the approved human-facing layout for typed Analysis visualizations. They are
not a mutation path. `.research/interface/` is generated, and the current `analysis-insight` payload
renders text fields only. Do not paste these snippets into the generated interface or store them as
raw HTML. Use them when the state schema and `lib.interface` renderer expose a typed visualization
field.

The renderer implementation uses inline HTML and CSS, with no external library, `<script>` block, or
canvas. Each visualization has one caption paragraph that starts with `<em>Reading:</em>`.

## Canonical color palette

| Role | Color |
| --- | --- |
| Card chrome: border | `#d8dde6` |
| Card chrome: background | `#fafbfd` |
| Card chrome: summary text | `#1f2a44` |
| Bar: background | `#eef` |
| Bar: border | `#ccd` |
| Bar fill: neutral / baseline | `#888` |
| Bar fill: pass / improved | `#4a8e63` |
| Bar fill: fail / regressed | `#a14444` |
| Threshold dashed line | `#c33` |
| Chip: pass (bg / text / border) | `#dff5e3` / `#0a5d24` / `#b8e5c2` |
| Chip: fail (bg / text / border) | `#fde2e2` / `#7a1a1a` / `#f0b8b8` |
| Caption | `font-size:0.88rem; color:#555;` |
| Heatmap gradient (best → worst) | `#fbe0db`, `#f4ada1`, `#e89486`, `#c8593f`, `#a93527`, `#8c2c1f`, `#691f15` |

When mapping a metric to a heatmap band, place the best value in the lightest band and the worst in the darkest. Use white text on bands `#c8593f` and darker; dark text (`#7a1a1a` or `#5a1010`) on the lighter bands.

---

## 1. Threshold bar chart

Use this pattern to show whether each cell crosses one admit/drop threshold. Give each cell one
horizontal bar, a vertical threshold line, and a verdict chip.

```html
<div style="display:grid; grid-template-columns: 150px 1fr 70px 70px; gap:6px 14px; align-items:center; font-size:0.9rem; margin:0.6em 0 0.2em 0;">
  <div style="font-weight:600; color:#555;">cell</div>
  <div style="font-weight:600; color:#555; position:relative;">
    <span style="position:absolute; left:0;">0%</span>
    <span style="position:absolute; left:30%; transform:translateX(-50%); color:#c33;">30%</span>
    <span style="position:absolute; right:0;">100%</span>
    &nbsp;
  </div>
  <div style="font-weight:600; color:#555; text-align:right;">value</div>
  <div style="font-weight:600; color:#555;">verdict</div>

  <div>cell-1</div>
  <div style="position:relative; background:#eef; height:16px; border:1px solid #ccd;">
    <div style="position:absolute; top:-3px; bottom:-3px; left:30%; border-left:2px dashed #c33;"></div>
    <div style="background:#4a8e63; width:1.06%; height:100%;"></div>
  </div>
  <div style="text-align:right; font-variant-numeric:tabular-nums;">1.06%</div>
  <div><span style="background:#dff5e3; color:#0a5d24; border:1px solid #b8e5c2; padding:1px 7px; border-radius:3px; font-size:0.8rem;">admit</span></div>

  <div>cell-2</div>
  <div style="position:relative; background:#eef; height:16px; border:1px solid #ccd;">
    <div style="position:absolute; top:-3px; bottom:-3px; left:30%; border-left:2px dashed #c33;"></div>
    <div style="background:#a14444; width:33.26%; height:100%;"></div>
  </div>
  <div style="text-align:right; font-variant-numeric:tabular-nums;">33.26%</div>
  <div><span style="background:#fde2e2; color:#7a1a1a; border:1px solid #f0b8b8; padding:1px 7px; border-radius:3px; font-size:0.8rem;">drop</span></div>
</div>
<p class="card-text" style="font-size:0.88rem; color:#555;"><em>Reading:</em> bars under the dashed line clear the threshold; bars over it fail it. Bar fill is green for pass cells, red for fail cells.</p>
```

Bar width is the value as a percentage of the scale from 0 to 100. For percentages, use
`width:VALUE%`. For raw counts, choose `MAX` and use `width:calc(VALUE / MAX * 100%)`.

---

## 2. Before/after paired-bar table

Use this pattern to compare two variants, such as a baseline and intervention, across several cells.
Each cell uses two stacked bars and one delta column spanning both rows.

```html
<table style="width:100%; border-collapse:collapse; font-size:0.88rem; margin:0.6em 0;">
  <thead>
    <tr style="background:#eef0f4;">
      <th style="padding:6px 10px; text-align:left; border-bottom:1px solid #d0d4d9;">cell</th>
      <th style="padding:6px 10px; text-align:left; border-bottom:1px solid #d0d4d9;">variant</th>
      <th style="padding:6px 10px; text-align:left; border-bottom:1px solid #d0d4d9;">metric (scale 0 to MAX)</th>
      <th style="padding:6px 10px; text-align:right; border-bottom:1px solid #d0d4d9;">value</th>
      <th style="padding:6px 10px; text-align:right; border-bottom:1px solid #d0d4d9;">Δ</th>
    </tr>
  </thead>
  <tbody>
    <tr style="border-top:1px solid #e2e6eb;">
      <td rowspan="2" style="padding:6px 10px; vertical-align:middle; font-weight:600;">cell-1</td>
      <td style="padding:4px 10px; color:#444;">baseline</td>
      <td style="padding:4px 10px;"><div style="background:#eef; height:14px; border:1px solid #ccd;"><div style="background:#888; width:42.7%; height:100%;"></div></div></td>
      <td style="padding:4px 10px; text-align:right; font-variant-numeric:tabular-nums;">106.83</td>
      <td rowspan="2" style="padding:6px 10px; text-align:right; vertical-align:middle; font-weight:700; color:#7a1a1a;">−29%</td>
    </tr>
    <tr>
      <td style="padding:4px 10px; color:#a14444;">variant</td>
      <td style="padding:4px 10px;"><div style="background:#eef; height:14px; border:1px solid #ccd;"><div style="background:#a14444; width:30.6%; height:100%;"></div></div></td>
      <td style="padding:4px 10px; text-align:right; font-variant-numeric:tabular-nums;">76.38</td>
    </tr>
    <!-- repeat the two-row block for each cell -->
  </tbody>
</table>
<p class="card-text" style="font-size:0.88rem; color:#555;"><em>Reading:</em> baseline (gray) vs variant (red), value column gives the raw number, Δ column gives the relative change. Use green (<code>#4a8e63</code>) for the variant bar when it improves, red (<code>#a14444</code>) when it regresses.</p>
```

Bar width math: `100 * VALUE / MAX`, where `MAX` is the chart's scale ceiling (set to slightly above the largest observed value).

---

## 3. Two-axis heatmap

Use this pattern to show a metric over a rows by columns grid, such as a dose-response sweep over two
controls. The color moves from light for the best value to dark for the worst. Use white text on the
darker bands.

```html
<div style="display:grid; grid-template-columns: 80px repeat(3, 1fr); gap:5px; max-width:560px; font-size:0.88rem; margin:0.6em 0;">
  <div></div>
  <div style="text-align:center; font-weight:600; color:#555;">col-A</div>
  <div style="text-align:center; font-weight:600; color:#555;">col-B</div>
  <div style="text-align:center; font-weight:600; color:#555;">col-C</div>

  <div style="font-weight:600; color:#555; align-self:center; text-align:right; padding-right:8px;">row-1</div>
  <div style="background:#fbe0db; padding:14px 8px; text-align:center; border-radius:4px; color:#7a1a1a;"><strong>−2.83</strong><br><span style="font-size:0.78rem;">best</span></div>
  <div style="background:#f4ada1; padding:14px 8px; text-align:center; border-radius:4px; color:#5a1010;"><strong>−3.43</strong></div>
  <div style="background:#e89486; padding:14px 8px; text-align:center; border-radius:4px; color:#3d0a0a;"><strong>−4.34</strong></div>

  <div style="font-weight:600; color:#555; align-self:center; text-align:right; padding-right:8px;">row-2</div>
  <div style="background:#c8593f; padding:14px 8px; text-align:center; border-radius:4px; color:#fff;"><strong>−8.15</strong></div>
  <div style="background:#a93527; padding:14px 8px; text-align:center; border-radius:4px; color:#fff;"><strong>−10.53</strong></div>
  <div style="background:#8c2c1f; padding:14px 8px; text-align:center; border-radius:4px; color:#fff;"><strong>−12.08</strong></div>

  <div style="font-weight:600; color:#555; align-self:center; text-align:right; padding-right:8px;">row-3</div>
  <div style="background:#a93527; padding:14px 8px; text-align:center; border-radius:4px; color:#fff;"><strong>−10.27</strong></div>
  <div style="background:#8c2c1f; padding:14px 8px; text-align:center; border-radius:4px; color:#fff;"><strong>−12.54</strong></div>
  <div style="background:#691f15; padding:14px 8px; text-align:center; border-radius:4px; color:#fff;"><strong>−14.79</strong><br><span style="font-size:0.78rem;">worst</span></div>
</div>
<p class="card-text" style="font-size:0.88rem; color:#555;"><em>Reading:</em> rows = one knob, columns = the other. Lightest cell is the best result; darkest is the worst. A monotonic gradient across either axis implies a dose-response.</p>
```

Pick exactly one band per value. Sort all values, then assign bands in order so the lightest band always holds the best value.

---

## 4. Single-axis dose-response bar chart

Use this pattern to show a metric across one control's settings. Put every bar on the same
absolute-value scale and darken the fill as severity increases.

```html
<div style="display:grid; grid-template-columns: 90px 1fr 80px; gap:6px 12px; align-items:center; font-size:0.88rem; max-width:560px; margin:0.6em 0;">
  <div style="font-weight:600; color:#555;">setting = 0</div>
  <div style="background:#eef; height:14px; border:1px solid #ccd;"><div style="background:#f4ada1; width:56.4%; height:100%;"></div></div>
  <div style="text-align:right; font-variant-numeric:tabular-nums; color:#7a1a1a;"><strong>−2.82</strong></div>

  <div style="font-weight:600; color:#555;">setting = 2</div>
  <div style="background:#eef; height:14px; border:1px solid #ccd;"><div style="background:#e89486; width:70.0%; height:100%;"></div></div>
  <div style="text-align:right; font-variant-numeric:tabular-nums; color:#7a1a1a;"><strong>−3.50</strong></div>

  <div style="font-weight:600; color:#555;">setting = 5</div>
  <div style="background:#eef; height:14px; border:1px solid #ccd;"><div style="background:#c8593f; width:78.8%; height:100%;"></div></div>
  <div style="text-align:right; font-variant-numeric:tabular-nums; color:#7a1a1a;"><strong>−3.94</strong></div>

  <div style="font-weight:600; color:#555;">setting = 10</div>
  <div style="background:#eef; height:14px; border:1px solid #ccd;"><div style="background:#a93527; width:93.0%; height:100%;"></div></div>
  <div style="text-align:right; font-variant-numeric:tabular-nums; color:#7a1a1a;"><strong>−4.65</strong></div>
</div>
<p class="card-text" style="font-size:0.88rem; color:#555;"><em>Reading:</em> bars show |Δmetric| on a 0 to MAX scale. The bar fill darkens monotonically with severity so the dose-response is visible at a glance.</p>
```

Pick `MAX = 1.1 × max(|value|)` so the worst bar visually fills most of the row.

---

## 5. Admission matrix (pass/drop grid)

Use this pattern to summarize a per-cell pass/drop verdict across two factors, such as dataset by
setting.

```html
<div style="display:grid; grid-template-columns: 90px repeat(4, 1fr); gap:6px; font-size:0.88rem; margin:0.6em 0 0.2em 0;">
  <div></div>
  <div style="font-weight:600; text-align:center;">col-1</div>
  <div style="font-weight:600; text-align:center;">col-2</div>
  <div style="font-weight:600; text-align:center;">col-3</div>
  <div style="font-weight:600; text-align:center;">col-4</div>

  <div style="font-weight:600; align-self:center;">row-A</div>
  <div style="background:#dff5e3; color:#0a5d24; border:1px solid #b8e5c2; padding:8px 6px; border-radius:4px; text-align:center;"><strong>admit</strong><br><span style="font-size:0.78rem;">k1 1.06%<br>k2 80.05%</span></div>
  <div style="background:#dff5e3; color:#0a5d24; border:1px solid #b8e5c2; padding:8px 6px; border-radius:4px; text-align:center;"><strong>admit</strong><br><span style="font-size:0.78rem;">k1 8.96%<br>k2 73.19%</span></div>
  <div style="background:#dff5e3; color:#0a5d24; border:1px solid #b8e5c2; padding:8px 6px; border-radius:4px; text-align:center;"><strong>admit</strong><br><span style="font-size:0.78rem;">k1 0.00%<br>k2 74.97%</span></div>
  <div style="background:#dff5e3; color:#0a5d24; border:1px solid #b8e5c2; padding:8px 6px; border-radius:4px; text-align:center;"><strong>admit</strong><br><span style="font-size:0.78rem;">k1 0.00%<br>k2 53.40%</span></div>

  <div style="font-weight:600; align-self:center;">row-B</div>
  <div style="background:#fde2e2; color:#7a1a1a; border:1px solid #f0b8b8; padding:8px 6px; border-radius:4px; text-align:center;"><strong>drop</strong><br><span style="font-size:0.78rem;">k1 <strong>33.26%</strong><br>k2 63.10%</span></div>
  <div style="background:#dff5e3; color:#0a5d24; border:1px solid #b8e5c2; padding:8px 6px; border-radius:4px; text-align:center;"><strong>admit</strong><br><span style="font-size:0.78rem;">k1 16.40%<br>k2 64.96%</span></div>
  <div style="background:#fde2e2; color:#7a1a1a; border:1px solid #f0b8b8; padding:8px 6px; border-radius:4px; text-align:center;"><strong>drop</strong><br><span style="font-size:0.78rem;">k1 <strong>31.13%</strong><br>k2 61.27%</span></div>
  <div style="background:#fde2e2; color:#7a1a1a; border:1px solid #f0b8b8; padding:8px 6px; border-radius:4px; text-align:center;"><strong>drop</strong><br><span style="font-size:0.78rem;">k1 <strong>73.85%</strong><br>k2 47.66%</span></div>
</div>
<p class="card-text" style="font-size:0.88rem; color:#555;"><em>Reading:</em> each cell shows the verdict plus the two binding numbers underneath. Bold the number that failed its threshold so the reader sees which check killed the cell.</p>
```

Bold (`<strong>`) only the failing metric inside a cell, never the cell verdict itself (the verdict color already encodes it).

---

## Caption discipline

Every visualization in the Insight block must be followed by exactly one caption. The caption is a single `<p>` with:

```
class="card-text" style="font-size:0.88rem; color:#555;"
```

and the body starts with `<em>Reading:</em>`. The state linter does not parse rendered HTML. The
typed visualization renderer must enforce this caption contract when that payload is introduced.
Keep the caption short: name the axes, identify the threshold or comparison, and state what the
chart implies in one sentence.
