(() => {
  "use strict";

  document.documentElement.classList.add("js");

  const messages = {
    "zh-CN": {
      title: "EasyFormat · 论文格式，轻松掌握",
      description: "EasyFormat — 让论文格式调整更省时、更清楚、更可控。",
      product: "产品简介",
      workflow: "技术设计与产品 workflow",
      ai: "AI选型&产品调优",
      business: "商业分析",
      skip: "跳到主要内容",
      home: "EasyFormat，返回顶部",
      navigation: "主要导航",
      language: "切换语言",
      openMenu: "打开导航菜单",
      closeMenu: "关闭导航菜单",
      "formats.status": "已显示 {count} 个格式类别。",
      "technical.confirm.ready": "已选择“{choice}”。确认后，此示例才进入下一步。",
      "technical.confirm.confirmed.simsun": "示意：已确认采用宋体，下一步为格式编辑。",
      "technical.confirm.confirmed.simhei": "示意：已确认采用黑体，下一步为格式编辑。",
      "technical.confirm.confirmed.skip": "示意：已明确暂时忽略，此项不执行并保留在报告中；其余已验证规则继续。",
    },
    en: {
      title: "EasyFormat · Thesis formatting, made simple",
      description: "EasyFormat — thesis formatting that saves time and keeps you in control.",
      product: "Product Overview",
      workflow: "Technical Design & Workflow",
      ai: "AI Selection & Product Tuning",
      business: "Business Analysis",
      skip: "Skip to main content",
      home: "EasyFormat, back to top",
      navigation: "Main navigation",
      language: "Switch language",
      openMenu: "Open navigation menu",
      closeMenu: "Close navigation menu",
      "hero.title": "“Format your thesis in one click with an AI assistant”",
      "hero.description": "Finishing your thesis is only part of the work. Fonts, headings, spacing, margins, contents and tables can still need repeated adjustments. EasyFormat connects your institution’s requirements with your document, reducing manual checks and repetitive edits.",
      "hero.explore": "Explore formatting",
      "hero.flow": "View the process",
      "hero.impact.start": "With EasyFormat, formatting and review time can go from",
      "hero.impact.hours": " hrs",
      "hero.impact.to": "to",
      "hero.impact.minutes": " min",
      "hero.impact.resolution": ", resolving",
      "hero.impact.issues": "of formatting issues within the supported scope on the first pass.",
      "flow.kicker": "PROCESS",
      "flow.title": "Upload your draft and requirements. Start with a click.",
      "flow.description": "Clarify what matters, then format automatically. Refine individual details after the first pass.",
      "flow.upload.title": "Upload your files",
      "flow.upload.description": "Upload your thesis draft and formatting requirements",
      "flow.upload.formats": "(DOCX and PDF formats supported)",
      "flow.format.title": "Clarify, then format",
      "flow.format.description": "Extract the rules, confirm uncertainties and apply reliable changes. With no questions to resolve, processing continues directly.",
      "flow.refine.title": "Preview and refine",
      "flow.refine.description": "Get an editable document, report and preview. Select text and describe a change to refine a specific area.",
      "assurance.versions": "Original and version history preserved",
      "assurance.evidence": "Reasons and locations for changes",
      "assurance.validation": "Validation results included",
      "formats.kicker": "FORMATTING CAPABILITIES",
      "formats.title": "From individual fonts to the entire layout.",
      "formats.description": "Bring common formal-document requirements into one workflow.",
      "formats.tag": "Whole-document formatting · Local refinement",
      "formats.filterLabel": "Filter formatting categories",
      "formats.all": "All formats",
      "formats.text": "Text & paragraphs",
      "formats.layout": "Page & structure",
      "formats.academic": "Figures & academic",
      "formats.status": "{count} format categories shown.",
      "formats.disclaimer": "Some features are still in development. Available functionality may change.",
      "format.font.title": "Fonts & characters",
      "format.font.description": "Font families and sizes, bold, italic, color, underline, strikethrough, superscript, subscript, character spacing and scaling; separate settings for Chinese, Latin text and numerals.",
      "format.paragraph.title": "Paragraphs",
      "format.paragraph.description": "Alignment, line and paragraph spacing, first-line, hanging and left/right indents, tab stops, leaders, borders, shading, widow/orphan control and pagination.",
      "format.heading.title": "Headings",
      "format.heading.description": "Fonts, sizes, styles, alignment, indents and spacing for each heading level; hierarchy, multilevel numbering, chapter starts and links to the table of contents.",
      "format.page.title": "Pages & sections",
      "format.page.description": "Paper size, orientation, margins, binding gutters, columns, text direction, mirrored margins, section breaks and chapter-specific settings.",
      "format.footer.title": "Headers, footers & pages",
      "format.footer.description": "Text appearance, position and offsets, page-number format and starting value, different first and odd/even pages, chapter headers and continuous numbering.",
      "format.contents.title": "Contents & references",
      "format.contents.description": "Contents levels and entry styles, conversion of manual contents, lists of figures and tables, cross-references and field updates.",
      "format.table.title": "Tables",
      "format.table.description": "Three-line, grid and borderless tables, cell text, row heights, column widths, cell margins and alignment, repeated header rows, page breaks and complex borders.",
      "format.image.title": "Images & captions",
      "format.image.description": "Image size, position, alignment and text wrapping; caption fonts, sizes, numbering, placement and spacing around figures.",
      "format.list.title": "Lists & numbering",
      "format.list.description": "Bullets, numbering styles, indents, numbering continuity, multilevel lists and list-text appearance.",
      "format.reference.title": "Notes, citations & bibliography",
      "format.reference.description": "Fonts, sizes, indents, spacing, footnote/endnote numbering, separator lines and visual consistency.",
      "format.equation.title": "Equations",
      "format.equation.description": "Fonts, sizes, alignment, numbering and spacing around equations.",
      "technical.title": "From requirements to verified changes.",
      "technical.description": "EasyFormat connects requirement parsing, document editing, preview and refinement in one workflow. AI interprets requirements, deterministic software applies changes, and evidence and versions follow every step.",
      "technical.architecture": "System architecture",
      "technical.architecture.tag": "One task · Three modules",
      "technical.parse.title": "Requirement parsing",
      "technical.edit.title": "Document editing",
      "technical.preview.title": "Preview & refinement",
      "technical.gate.link": "Explore the confirmation example →",
      "technical.foundation.title": "Workflow and version management",
      "technical.foundation.description": "Immutable original · Rule snapshots · Independent versions",
      "technical.parse.subtitle": "Stable, efficient and reusable Brief Parsing.",
      "technical.parse.evidence.title": "Grounded in source evidence",
      "technical.parse.evidence.description": "Distinguish explicit requirements, template observations and examples. Link each candidate to real source evidence; missing or unsupported information remains pending clarification.",
      "technical.parse.schema.title": "Schema and semantic validation",
      "technical.parse.schema.description": "Constrain the output with JSON Schema, then verify objects, attributes, values, units, conditions and scope so software can process the rules.",
      "technical.parse.budget.title": "Separate stages, controlled cost",
      "technical.parse.budget.description": "Extraction, coverage auditing and dispute analysis have separate roles. Set timeouts, bounded retries and token budgets, and reuse validated parsing results.",
      "technical.parse.reuse.title": "Versioned interfaces for reuse",
      "technical.parse.reuse.description": "Pin model and prompt versions. Connect to different hosts through parse bundles, domain packs and model adapters, with clear input, output and validation boundaries.",
      "technical.proof.source": "SOURCE EVIDENCE · E-001",
      "technical.proof.quote": "“Use SimSun for body text.”",
      "technical.proof.description": "Candidate values need source support. Template observations retain their own provenance.",
      "technical.proof.schema": "STRUCTURED OUTPUT · SIMPLIFIED EXAMPLE",
      "technical.proof.code": "{\n  \"object\": \"body\",\n  \"attribute\": \"font\",\n  \"value\": \"SimSun\",\n  \"evidence\": \"E-001\"\n}",
      "technical.confirm.title": "Resolve questions before making changes.",
      "technical.confirm.badge": "Interactive example",
      "technical.confirm.question": "Two font requirements conflict. Which should apply to body text?",
      "technical.confirm.evidence1": "Requirement A: use SimSun.",
      "technical.confirm.evidence2": "Requirement B: use SimHei.",
      "technical.confirm.legend": "Choose a font requirement or explicitly skip",
      "technical.confirm.simsun": "Use SimSun",
      "technical.confirm.simhei": "Use SimHei",
      "technical.confirm.skip": "Skip this question for now",
      "technical.confirm.submit": "Confirm selection (demo)",
      "technical.confirm.reset": "Reset example",
      "technical.confirm.pending": "Choose an option. Editing waits while this question is unanswered.",
      "technical.confirm.ready": "Selected: {choice}. Confirm to continue this example.",
      "technical.confirm.confirmed.simsun": "Demo: SimSun confirmed. The next stage is document editing.",
      "technical.confirm.confirmed.simhei": "Demo: SimHei confirmed. The next stage is document editing.",
      "technical.confirm.confirmed.skip": "Demo: explicitly skipped. This item stays unchanged and is recorded in the report; other validated rules can proceed.",
      "technical.confirm.footnote": "Reliable explicit rules need no item-by-item approval. Skipping does not create a default rule; the item remains in the report.",
      "technical.edit.subtitle": "Deterministic edits. Individual validation.",
      "technical.edit.rules.title": "Only validated rules reach the editor",
      "technical.edit.rules.description": "Translate typed rules into object mapping and an edit plan. Apply specific properties within their scope, preserving meaning, table data and citation content.",
      "technical.edit.versions.title": "Every edit creates a separate version",
      "technical.edit.versions.description": "Keep V0 and published history unchanged. Create a new file from the selected parent version and bind its rule snapshot to the edit, preventing stale results after an answer changes.",
      "technical.edit.validation.title": "Reopen and validate after saving",
      "technical.edit.validation.description": "Check actual formatting, document structure and text again. Record the location, evidence and validation outcome of each change for traceability.",
      "technical.edit.efficiency.title": "Clear execution boundaries, less rework",
      "technical.edit.efficiency.description": "Separate rule interpretation from document execution. Clarify unreliable locations, ambiguous conditions or conflicts before submitting a reliable edit plan.",
      "technical.edit.sequenceLabel": "Document editing steps",
      "technical.edit.locate": "Locate objects",
      "technical.edit.plan": "Build the plan",
      "technical.edit.apply": "Edit a copy",
      "technical.edit.verify": "Reopen and validate",
      "technical.preview.subtitle": "See the result. Refine the details.",
      "technical.preview.visible.title": "Preview, report and version together",
      "technical.preview.visible.description": "Generate PDFs with LibreOffice and use PDF.js to browse, zoom and select text. Review the reasons for changes and download an editable DOCX.",
      "technical.preview.scope.title": "Start refining at your selection",
      "technical.preview.scope.description": "Select text and describe a change with a clear scope. Paragraph properties identify the containing paragraph; broader scope, ambiguous locations or conflicts require clarification.",
      "technical.preview.reuse.title": "Lightweight parsing, reusable results",
      "technical.preview.reuse.description": "Reuse formatting rules and validation for local feedback, alongside verified parsing results and decision snapshots, reducing repeated calls over the full requirements document.",
      "technical.preview.history.title": "Keep refining with traceable history",
      "technical.preview.history.description": "Publish a separate document, report and preview for every refinement. Review history and choose any version as the starting point for further changes.",
      "technical.preview.loop": "Selection and request → Lightweight parsing and scope checks → Necessary clarification → Document editing → New-version preview",
      "technical.prototype.kicker": "PRODUCT PROTOTYPE",
      "technical.prototype.title": "Bring the complete workflow into view.",
      "technical.prototype.placeholder": "Product prototype showcase",
      "technical.prototype.description": "Reserved for an actual walkthrough, interactive prototype or screenshots.",
      "technical.prototype.path": "Upload files → Clarify before editing → Preview and report → Local refinement → Version history",
      "technical.chart.summary": "Upload a thesis draft and institution requirements, then extract evidence and validate. If questions remain, show evidence and options, collect an answer or explicit skip, and check again. Once no questions remain, locate objects, edit and validate. Publish a document version, preview and report. Download the result or submit local feedback, check its scope and clarify as needed, then return validated rules to document editing.",
      "technical.chart.upload": "Upload thesis draft and institution requirements",
      "technical.chart.extract": "Extract requirements and source evidence",
      "technical.chart.validate": "Schema and semantic validation",
      "technical.chart.question": "Questions remaining?",
      "technical.chart.show": "Show evidence and candidate answers",
      "technical.chart.show.detail": "Include an explicit skip option",
      "technical.chart.answer": "User answers each question",
      "technical.chart.answer.detail": "Or explicitly skips the item",
      "technical.chart.locate": "Locate objects and build an edit plan",
      "technical.chart.edit": "Edit a copy and validate",
      "technical.chart.preview": "Draft or new version, preview and report",
      "technical.chart.download": "Download result",
      "technical.chart.refine": "Local selection and refinement request",
      "technical.chart.feedback": "Lightweight parsing, scope checks and necessary clarification",
      "technical.chart.yes": "Yes",
      "technical.chart.no": "No questions remaining",
      "technical.chart.recheck": "Check again",
      "technical.chart.verified": "Validated rules",
      "technical.chart.waiting": "Unanswered questions keep editing on hold. All pending items must be answered or explicitly skipped before editing.",
      "technical.chart.legend.main": "Main workflow",
      "technical.chart.legend.confirm": "Pre-edit confirmation loop",
      "technical.chart.legend.refine": "Local refinement loop",
      "technical.dialog.kicker": "MODULE DETAILS",
      "technical.dialog.openHint": "(Click for details)",
      "technical.dialog.close": "Close module details",
      "technical.dialog.content": "Detailed module introduction",
      "technical.dialog.hint": "Click outside the card, or keep scrolling down after the content ends, to return to the workflow.",
    },
  };

  // Chinese copy lives in the HTML so it remains readable without JavaScript.
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const key = element.dataset.i18n;
    if (!Object.hasOwn(messages["zh-CN"], key)) messages["zh-CN"][key] = element.textContent;
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
    const key = element.dataset.i18nAria;
    if (!Object.hasOwn(messages["zh-CN"], key)) messages["zh-CN"][key] = element.getAttribute("aria-label");
  });

  const header = document.querySelector(".site-header");
  const menuToggle = document.querySelector(".menu-toggle");
  const navigation = document.querySelector(".site-nav");
  const links = [...document.querySelectorAll(".nav-link")];
  const sections = [...document.querySelectorAll(".page-section")];
  const languageButtons = [...document.querySelectorAll("[data-language]")];
  const filterButtons = [...document.querySelectorAll("[data-format-filter]")];
  const formatRows = [...document.querySelectorAll("[data-format-group]")];
  const compactLayout = window.matchMedia("(max-width: 1120px)");
  const storageKey = "easyformat-site-language";
  const confirmationForm = document.getElementById("confirmation-demo");
  let confirmedDemoChoice = null;
  let language = "zh-CN";
  let activeSection = "";
  let scrollQueued = false;
  let formatFilter = "all";

  function updateFormatStatus() {
    const count = formatRows.filter((row) => !row.hidden).length;
    document.getElementById("format-status").textContent = messages[language]["formats.status"].replace("{count}", count);
  }

  function filterFormats(nextFilter) {
    formatFilter = nextFilter;
    formatRows.forEach((row) => { row.hidden = formatFilter !== "all" && row.dataset.formatGroup !== formatFilter; });
    filterButtons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.formatFilter === formatFilter)));
    updateFormatStatus();
    queuePositionUpdate();
  }

  function updateConfirmationDemo() {
    if (!confirmationForm) return;
    const selected = confirmationForm.querySelector('input[name="font-rule"]:checked');
    const copy = messages[language];
    const status = confirmationForm.querySelector(".confirmation-status");
    confirmationForm.querySelector('[type="submit"]').disabled = !selected;
    if (selected && confirmedDemoChoice === selected.value) {
      status.textContent = copy[`technical.confirm.confirmed.${selected.value}`];
      confirmationForm.dataset.state = "confirmed";
    } else if (selected) {
      status.textContent = copy["technical.confirm.ready"].replace("{choice}", copy[`technical.confirm.${selected.value}`]);
      confirmationForm.dataset.state = "ready";
    } else {
      status.textContent = copy["technical.confirm.pending"];
      confirmationForm.dataset.state = "pending";
    }
  }

  function setMenu(open, restoreFocus = false) {
    header.dataset.menuOpen = String(open);
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", messages[language][open ? "closeMenu" : "openMenu"]);
    menuToggle.dataset.i18nAria = open ? "closeMenu" : "openMenu";
    if (restoreFocus) menuToggle.focus({ preventScroll: true });
  }

  function setLanguage(nextLanguage, persist = true) {
    if (!Object.hasOwn(messages, nextLanguage)) return;
    language = nextLanguage;
    const copy = messages[language];
    document.documentElement.lang = language;
    document.title = copy.title;
    document.querySelector('meta[name="description"]').content = copy.description;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const text = copy[element.dataset.i18n] ?? messages["zh-CN"][element.dataset.i18n];
      if (text) element.textContent = text;
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
      const text = copy[element.dataset.i18nAria] ?? messages["zh-CN"][element.dataset.i18nAria];
      if (text) element.setAttribute("aria-label", text);
    });
    languageButtons.forEach((button) => {
      button.disabled = false;
      button.setAttribute("aria-pressed", String(button.dataset.language === language));
    });
    updateFormatStatus();
    updateConfirmationDemo();
    queuePositionUpdate();
    document.dispatchEvent(new Event("easyformat:languagechange"));
    if (persist) {
      try { localStorage.setItem(storageKey, language); } catch { /* The switch still works without storage. */ }
    }
  }

  function updatePosition() {
    scrollQueued = false;
    header.dataset.scrolled = String(window.scrollY > 12);
    const readingLine = header.offsetHeight + window.innerHeight * 0.32;
    let current = sections[0];
    for (const section of sections) {
      if (section.getBoundingClientRect().top <= readingLine) current = section;
    }
    if (current.id === activeSection) return;
    activeSection = current.id;
    document.documentElement.dataset.section = activeSection;
    links.forEach((link) => {
      if (link.hash === `#${activeSection}`) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }

  function queuePositionUpdate() {
    if (scrollQueued) return;
    scrollQueued = true;
    requestAnimationFrame(updatePosition);
  }

  languageButtons.forEach((button) => {
    button.addEventListener("click", () => setLanguage(button.dataset.language));
  });
  filterButtons.forEach((button) => button.addEventListener("click", () => filterFormats(button.dataset.formatFilter)));
  confirmationForm.addEventListener("change", () => {
    confirmedDemoChoice = null;
    updateConfirmationDemo();
  });
  confirmationForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const selected = confirmationForm.querySelector('input[name="font-rule"]:checked');
    if (!selected) return;
    confirmedDemoChoice = selected.value;
    updateConfirmationDemo();
  });
  confirmationForm.addEventListener("reset", () => {
    confirmedDemoChoice = null;
    requestAnimationFrame(updateConfirmationDemo);
  });
  menuToggle.addEventListener("click", () => setMenu(header.dataset.menuOpen !== "true"));
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) setMenu(false);
  });
  document.querySelector(".wordmark").addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && header.dataset.menuOpen === "true") setMenu(false, true);
  });
  document.addEventListener("click", (event) => {
    if (header.dataset.menuOpen === "true" && !header.contains(event.target)) setMenu(false);
  });
  document.addEventListener("focusin", (event) => {
    if (header.dataset.menuOpen === "true" && !header.contains(event.target)) setMenu(false);
  });
  compactLayout.addEventListener("change", () => setMenu(false));
  window.addEventListener("scroll", queuePositionUpdate, { passive: true });
  window.addEventListener("resize", queuePositionUpdate, { passive: true });
  window.addEventListener("pageshow", queuePositionUpdate);

  let storedLanguage;
  try { storedLanguage = localStorage.getItem(storageKey); } catch { /* Default to Chinese. */ }
  setLanguage(Object.hasOwn(messages, storedLanguage) ? storedLanguage : "zh-CN", false);
  updatePosition();

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (typeof IntersectionObserver === "function" && !reducedMotion.matches) {
    function observeOnce(selector, options) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      }, options);
      document.querySelectorAll(selector).forEach((element) => observer.observe(element));
    }
    observeOnce(".reveal", { threshold: 0.08, rootMargin: "0px 0px -20px 0px" });
    observeOnce(".flow-steps", { threshold: 0.15, rootMargin: "0px 0px -64px 0px" });
    observeOnce(".workflow-graph", { threshold: 0.1, rootMargin: "0px 0px -32px 0px" });
    document.documentElement.classList.add("motion-ready");
    reducedMotion.addEventListener("change", (event) => {
      if (event.matches) document.documentElement.classList.remove("motion-ready");
    });
  }
})();
