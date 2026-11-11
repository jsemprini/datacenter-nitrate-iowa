// Shared helpers and data loading for the document builders. Every number that appears in the
// documents is read from results/ or audit/ so text and analysis outputs cannot drift apart.
const fs = require("fs");
const path = require("path");
const d = require("docx");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, Header, Footer,
  AlignmentType, HeadingLevel, WidthType, ShadingType, BorderStyle, LevelFormat, PageNumber,
  ExternalHyperlink, TabStopType,
} = d;

const ROOT = path.resolve(__dirname, "..", "..");
const J = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), "utf8"));

function csv(p) {
  const txt = fs.readFileSync(path.join(ROOT, p), "utf8").trim().split(/\r?\n/);
  const split = (line) => {
    const out = []; let cur = ""; let q = false;
    for (const ch of line) {
      if (ch === '"') { q = !q; continue; }
      if (ch === "," && !q) { out.push(cur); cur = ""; continue; }
      cur += ch;
    }
    out.push(cur); return out;
  };
  const head = split(txt[0]);
  return txt.slice(1).map((l) => { const v = split(l); const o = {}; head.forEach((h, i) => (o[h] = v[i])); return o; });
}

const R = J("results/results.json");
const A = J("audit/audit_results.json");
const C = J("data/clean/cleaning_summary.json");
const V = J("results/verification_report.json");
const T2 = csv("results/tables/table2_main_estimates.csv");
const T3 = csv("results/tables/table3_sensitivity.csv");
const T3b = csv("results/tables/table3b_negative_control.csv");
const T4 = csv("results/tables/table4_mass_balance.csv");
const CAMP = csv("data/reference/hyperscale_campuses.csv");
const DATES = csv("audit/original_vs_documented_campus_dates.csv");
const SERIES = csv("results/tables/selected_system_series.csv");

// ---------------------------------------------------------------- number formatting
const num = (x) => (x === null || x === undefined || x === "" || x === "None" ? null : Number(x));
const f = (x, k = 2) => {
  const v = num(x); if (v === null || Number.isNaN(v)) return "—";
  const s = v.toFixed(k); return (s.startsWith("-") ? "−" + s.slice(1) : s);
};
const fp = (x) => { const v = num(x); if (v === null) return "—"; return v < 0.001 ? "<0.001" : v.toFixed(v < 0.1 ? 3 : 2); };
const pct = (x, k = 0) => (num(x) * 100).toFixed(k) + "%";
const ci = (lo, hi, k = 2) => `${lo === null || lo === undefined || lo === "" ? "below −6" : f(lo, k)} to ${hi === null || hi === undefined || hi === "" ? "above 6" : f(hi, k)}`;
const comma = (x) => Number(x).toLocaleString("en-US");

// ---------------------------------------------------------------- styles & primitives
const FONT = "Arial";
const INK = "1A1A1A";
const MUTED = "555555";
const ACCENT = "1F4E79";

function styles() {
  return {
    default: { document: { run: { font: FONT, size: 21, color: INK } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { font: FONT, size: 34, bold: true, color: INK },
        paragraph: { spacing: { before: 0, after: 120 }, keepNext: true } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 26, bold: true, color: ACCENT },
        paragraph: { spacing: { before: 300, after: 120 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 22, bold: true, color: INK },
        paragraph: { spacing: { before: 220, after: 80 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 21, bold: true, italics: true, color: INK },
        paragraph: { spacing: { before: 160, after: 60 }, keepNext: true, outlineLevel: 2 } },
    ],
  };
}

function numbering() {
  return {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
      ...Array.from({ length: 12 }, (_, i) => ({ reference: `num${i}`, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] })),
    ],
  };
}

// Inline markup: **bold**, *italic*, `code`. Returns TextRuns.
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0; let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), font: "Courier New", size: (base.size || 21) - 2, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const P = (text, opt = {}) => new Paragraph({
  children: runs(text, opt.run || {}), alignment: opt.align || AlignmentType.LEFT,
  spacing: { after: opt.after ?? 120, before: opt.before ?? 0, line: opt.line ?? 276 }, keepNext: opt.keepNext,
  indent: opt.indent,
});
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const H3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] });
const B = (text, ref = "bullets") => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(text),
  spacing: { after: 60, line: 264 } });
const N = (text, ref = "numbers") => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(text),
  spacing: { after: 80, line: 264 } });
const small = (text, opt = {}) => P(text, { run: { size: 17, color: MUTED }, after: opt.after ?? 160, keepNext: opt.keepNext });
const caption = (label, text) => new Paragraph({ children: [new TextRun({ text: label + " ", bold: true, size: 18 }), ...runs(text, { size: 18 })],
  spacing: { before: 60, after: 80 }, keepNext: true });

const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };

function table(headers, rows, widths, opt = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const sz = opt.size || 17;
  const mk = (txt, w, head, align) => new TableCell({
    borders, width: { size: w, type: WidthType.DXA },
    shading: head ? { fill: "E8EEF4", type: ShadingType.CLEAR } : undefined,
    margins: { top: 50, bottom: 50, left: 80, right: 80 },
    children: String(txt).split("\n").map((line) => new Paragraph({ children: runs(line, { size: sz, bold: head || undefined }),
      alignment: align || AlignmentType.LEFT, spacing: { after: 0, line: 240 } })),
  });
  const aligns = opt.aligns || headers.map(() => AlignmentType.LEFT);
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => mk(h, widths[i], true, aligns[i])) }),
      ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => mk(c, widths[i], false, aligns[i])) })),
    ],
  });
}

function figure(file, widthIn = 6.5) {
  const p = path.join(ROOT, "results/figures", file);
  const buf = fs.readFileSync(p);
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20); // PNG IHDR
  const W = Math.round(widthIn * 96), H = Math.round(W * h / w);
  return new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 40 },
    children: [new ImageRun({ type: "png", data: buf, transformation: { width: W, height: H },
      altText: { title: file, description: file, name: file } })] });
}

function doc(children, title, headerText) {
  return new Document({
    creator: "datacenter-nitrate-iowa replication (3-claude)", title, styles: styles(), numbering: numbering(),
    sections: [{
      properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1260, bottom: 1260, left: 1440, right: 1440 } } },
      headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
        children: [new TextRun({ text: headerText, size: 16, color: MUTED })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED })] })] }) },
      children,
    }],
  });
}

async function save(document, outPath) {
  const buf = await Packer.toBuffer(document);
  fs.mkdirSync(path.dirname(path.join(ROOT, outPath)), { recursive: true });
  fs.writeFileSync(path.join(ROOT, outPath), buf);
  console.log("wrote", outPath);
}

module.exports = { d, ROOT, R, A, C, V, T2, T3, T3b, T4, CAMP, DATES, SERIES, f, fp, pct, ci, comma, num, P, H1, H2, H3, B, N,
  small, caption, table, figure, doc, save, runs, AlignmentType, TextRun, Paragraph, ExternalHyperlink };
