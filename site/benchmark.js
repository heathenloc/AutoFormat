(() => {
  "use strict";
  const section = document.getElementById("ai");
  const data = window.autoformatBenchmarkData;
  if (!section || !data) return;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const copy = {
    "zh-CN": {
      before: "优化前", after: "优化后", higher: "越高越好", lower: "越低越好",
      points: "分", percentagePoints: "个百分点", improvement: "改善", increase: "提升", reduction: "减少", regression: "退步", unchanged: "无变化", unavailable: "待对比",
      latency: "耗时降低", latencyRegression: "耗时增加", tokens: "Token 减少", tokensRegression: "Token 增加",
      method: "调优方法", scale: "条形范围",
    },
    en: {
      before: "Before", after: "After", higher: "Higher is better", lower: "Lower is better",
      points: "pts", percentagePoints: "pp", improvement: "Improvement", increase: "Increase", reduction: "Reduction", regression: "Regression", unchanged: "No change", unavailable: "Not comparable",
      latency: "Faster", latencyRegression: "Slower", tokens: "Fewer Tokens", tokensRegression: "More Tokens",
      method: "Tuning methods", scale: "Bar range",
    },
  };
  const records = [];
  const tooltip = document.createElement("div");
  tooltip.className = "benchmark-tooltip";
  tooltip.id = "benchmark-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  document.body.append(tooltip);
  let tooltipRecord = null;
  const language = () => document.documentElement.lang === "en" ? "en" : "zh-CN";
  const text = () => copy[language()];

  function formatValue(value, item) {
    const options = { minimumFractionDigits: item.precision, maximumFractionDigits: item.precision };
    if (item.format === "currency") Object.assign(options, { style: "currency", currency: item.currency, currencyDisplay: "narrowSymbol" });
    const number = new Intl.NumberFormat(language(), options).format(value);
    return number + (item.format === "percent" ? "%" : item.format === "seconds" ? "s" : "");
  }

  function change(item) {
    const difference = item.after - item.before;
    const positive = item.direction === "higher" ? difference > 0 : difference < 0;
    const trend = difference === 0 ? "neutral" : positive ? "improvement" : "regression";
    const c = text();
    let number, unit = "", caption, full;
    if (item.improvement.mode === "points") {
      const points = difference * item.improvement.multiplier;
      number = (points > 0 ? "+" : points < 0 ? "−" : "") + Math.abs(Math.round(points));
      unit = c[item.improvement.unit];
      caption = difference === 0 ? c.unchanged : positive ? c.increase : c.regression;
      if (item.improvement.presentation === "arrowPercent") {
        // Keep the precise percentage-point unit in the tooltip while using the requested compact badge.
        full = `${number} ${unit}`;
        number = `${points < 0 ? "↓" : points > 0 ? "↑" : ""}${Math.abs(Math.round(points))}`;
        unit = "%";
      }
    } else {
      const percent = item.before === 0 ? null : Math.round(Math.abs(difference / item.before) * 100);
      number = percent === null ? "—" : `${difference < 0 ? "↓" : difference > 0 ? "↑" : ""}${percent}`;
      unit = percent === null ? "" : "%";
      caption = percent === null ? c.unavailable : difference === 0 ? c.unchanged : item.key === "latency" || item.key === "tokens" ? c[item.key + (positive ? "" : "Regression")] : positive ? c.reduction : c.regression;
    }
    return { number, unit, caption, trend, full: full || `${number}${unit === "%" ? "" : " "}${unit}`.trim() };
  }

  function setValues(record, beforeProgress, afterProgress) {
    record.beforeProgress = beforeProgress;
    record.afterProgress = afterProgress;
    for (const series of ["before", "after"]) {
      const progress = series === "before" ? beforeProgress : afterProgress;
      record.element.querySelector(`[data-series="${series}"] .benchmark-value`).textContent = formatValue(record.item[series] * progress, record.item);
      const dimension = record.group === "efficiency" ? "height" : "width";
      record.element.querySelector(`[data-series="${series}"] .benchmark-fill`).style[dimension] = `${Math.min(100, record.item[series] / record.scale * 100) * progress}%`;
    }
  }

  function updateText(record) {
    const c = text();
    const metricCopy = record.item.copy[language()];
    record.element.querySelector("h4").textContent = metricCopy.label;
    record.element.querySelector(".benchmark-metric-description").textContent = metricCopy.description;
    record.element.querySelector(".benchmark-direction").textContent = c[record.item.direction];
    for (const series of ["before", "after"]) {
      record.element.querySelector(`[data-series="${series}"] .benchmark-series-label`).textContent = c[series];
      record.element.querySelector(`[data-series="${series}"] .benchmark-final-value`).textContent = formatValue(record.item[series], record.item);
    }
    const improvement = change(record.item);
    record.element.dataset.trend = improvement.trend;
    record.element.querySelector(".benchmark-change-number").textContent = improvement.number;
    record.element.querySelector(".benchmark-change-unit").textContent = improvement.unit;
    const caption = record.element.querySelector(".benchmark-change-caption");
    if (caption) caption.textContent = improvement.caption;
    setValues(record, record.beforeProgress, record.afterProgress);
  }

  function buildMetric(item, group) {
    const element = document.createElement("article");
    element.className = `benchmark-metric benchmark-${group === "quality" ? "quality-metric" : "efficiency-card"}`;
    element.dataset.metric = item.key;
    const seriesMarkup = series => `<div class="benchmark-series benchmark-series-${series}" data-series="${series}"><span class="benchmark-series-label"></span><span class="benchmark-value" aria-hidden="true"></span><span class="benchmark-final-value sr-only"></span><span class="benchmark-track" aria-hidden="true"><span class="benchmark-fill"></span></span></div>`;
    const seriesOrder = group === "quality" ? ["after", "before"] : ["before", "after"];
    element.innerHTML = `<div class="benchmark-metric-heading"><h4 id="benchmark-${item.key}-heading"></h4><p class="benchmark-metric-description"></p><span class="benchmark-direction"></span></div>
      <div class="benchmark-comparison" tabindex="0" role="group" aria-labelledby="benchmark-${item.key}-heading">
        ${seriesOrder.map(seriesMarkup).join("")}
      </div>
      <div class="benchmark-improvement"><span class="benchmark-change"><span class="benchmark-change-number"></span><span class="benchmark-change-unit"></span></span>${group === "efficiency" ? '<span class="benchmark-change-caption"></span>' : ""}</div>`;
    if (group === "efficiency") element.querySelector(".benchmark-metric-heading").insertBefore(element.querySelector(".benchmark-direction"), element.querySelector(".benchmark-metric-description"));
    const record = { element, item, group, scale: Math.max(item.scaleMax || 0, item.before, item.after, Number.EPSILON), beforeProgress: 1, afterProgress: 1, started: false, frame: null };
    updateText(record);
    const comparison = element.querySelector(".benchmark-comparison");
    comparison.addEventListener("pointerenter", event => { if (event.pointerType === "mouse") showTooltip(record); });
    comparison.addEventListener("pointerleave", () => { if (!comparison.contains(document.activeElement)) hideTooltip(); });
    comparison.addEventListener("focus", () => showTooltip(record));
    comparison.addEventListener("blur", hideTooltip);
    records.push(record);
    document.getElementById(`benchmark-${group}-metrics`).append(element);
  }
  data.quality.forEach(item => buildMetric(item, "quality"));
  data.efficiency.forEach(item => buildMetric(item, "efficiency"));

  function showTooltip(record) {
    hideTooltip();
    tooltipRecord = record;
    const c = text();
    const metricCopy = record.item.copy[language()];
    tooltip.innerHTML = "<strong></strong><p class='benchmark-tip-description'></p><dl></dl><p class='benchmark-tip-direction'></p><p class='benchmark-tip-method'></p><p class='benchmark-tip-scale'></p>";
    tooltip.querySelector("strong").textContent = metricCopy.label;
    tooltip.querySelector(".benchmark-tip-description").textContent = metricCopy.description;
    for (const [label, value] of [[c.before, formatValue(record.item.before, record.item)], [c.after, formatValue(record.item.after, record.item)], [c.improvement, change(record.item).full]]) {
      const term = document.createElement("dt"), detail = document.createElement("dd");
      term.textContent = label;
      detail.textContent = value;
      tooltip.querySelector("dl").append(term, detail);
    }
    tooltip.querySelector(".benchmark-tip-direction").textContent = c[record.item.direction];
    tooltip.querySelector(".benchmark-tip-method").textContent = `${c.method} · ${metricCopy.method}`;
    tooltip.querySelector(".benchmark-tip-scale").textContent = `${c.scale} · ${formatValue(0, record.item)} – ${formatValue(record.scale, record.item)}`;
    tooltip.hidden = false;
    const comparison = record.element.querySelector(".benchmark-comparison");
    comparison.setAttribute("aria-describedby", tooltip.id);
    const origin = comparison.getBoundingClientRect(), bounds = tooltip.getBoundingClientRect();
    const left = Math.max(16, Math.min(innerWidth - bounds.width - 16, origin.left + origin.width / 2 - bounds.width / 2));
    const top = origin.bottom + bounds.height + 28 > innerHeight ? Math.max(16, origin.top - bounds.height - 12) : origin.bottom + 12;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function hideTooltip() {
    tooltipRecord?.element.querySelector(".benchmark-comparison").removeAttribute("aria-describedby");
    tooltip.hidden = true;
    tooltipRecord = null;
  }

  function finish(record) {
    if (record.frame !== null) cancelAnimationFrame(record.frame);
    record.frame = null;
    record.started = true;
    setValues(record, 1, 1);
    record.element.classList.add("is-settled");
  }

  function animate(record, delay = 0) {
    if (record.started) return;
    record.started = true;
    const start = performance.now() + delay;
    const ease = value => 1 - Math.pow(1 - Math.max(0, Math.min(1, value)), 3);
    function tick(now) {
      const elapsed = now - start;
      setValues(record, ease(elapsed / 850), ease((elapsed - 150) / 850));
      if (elapsed >= 1000) finish(record);
      else record.frame = requestAnimationFrame(tick);
    }
    record.frame = requestAnimationFrame(tick);
  }

  function updateLanguage() {
    records.forEach(updateText);
    if (data.methodology?.[language()]) document.getElementById("benchmark-data-note").textContent = data.methodology[language()];
    if (tooltipRecord) showTooltip(tooltipRecord);
  }
  document.addEventListener("autoformat:languagechange", updateLanguage);
  window.addEventListener("scroll", hideTooltip, { passive: true });
  window.addEventListener("resize", hideTooltip, { passive: true });
  document.addEventListener("keydown", event => { if (event.key === "Escape") hideTooltip(); });
  updateLanguage();

  if (!reducedMotion.matches && typeof IntersectionObserver === "function") {
    section.classList.add("benchmark-motion");
    records.forEach(record => setValues(record, 0, 0));
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        if (entry.target.classList.contains("benchmark-quality-card")) records.filter(record => data.quality.includes(record.item)).forEach((record, index) => animate(record, index * 60));
        else animate(records.find(record => record.element === entry.target));
        observer.unobserve(entry.target);
      }
    }, { threshold: 0.22, rootMargin: "0px 0px -24px 0px" });
    observer.observe(section.querySelector(".benchmark-quality-card"));
    records.filter(record => data.efficiency.includes(record.item)).forEach(record => observer.observe(record.element));
    reducedMotion.addEventListener("change", event => {
      if (!event.matches) return;
      observer.disconnect();
      records.forEach(finish);
      section.classList.remove("benchmark-motion");
    });
  } else records.forEach(finish);
})();
