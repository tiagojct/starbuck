import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import markdownIt from "markdown-it";
import markdownItAnchor from "markdown-it-anchor";

const ROOT = import.meta.dirname;
const PKG = path.join(ROOT, "..");

const LABELS = {
	none: "Correct reference (expected: Pass)", retracted: "Retracted work", expression_of_concern: "Expression of concern",
	corrected: "Corrected work", preprint_published: "Preprint with a published version", fabricated_doi: "Fabricated DOI",
	doi_of_other_paper: "DOI of another paper", pmid_of_other_paper: "PMID of another paper",
	doi_pmid_disagree: "DOI and PMID of two papers", wrong_year: "Wrong year", wrong_first_author: "Wrong first author",
	author_order: "First two authors swapped", no_identifier_real: "Real work, no identifier",
	no_identifier_invented: "Invented work, no identifier", dead_web_page: "Web page that is gone",
};

/** The newest live validation run (validation/results/<date>[-<version>]-scores.md, not a replay). */
function validation() {
	const dir = path.join(PKG, "validation", "results");
	const NAME = /^(\d{4}-\d{2}-\d{2})(?:-(\d+)\.(\d+)\.(\d+))?-scores\.md$/;
	const order = (f) => {
		const m = f.match(NAME);
		return [m[1], ...[m[2], m[3], m[4]].map((x) => String(+(x || 0)).padStart(6, "0"))].join(" ");
	};
	const runs = fs.readdirSync(dir).filter((f) => NAME.test(f)).sort((a, b) => order(a).localeCompare(order(b)));
	const text = fs.readFileSync(path.join(dir, runs.at(-1)), "utf8");
	const line = (label) => {
		const m = text.match(new RegExp(`${label}[^:]*: (\\d+)/(\\d+) = ([\\d.]+)% \\(([\\d.]+) to ([\\d.]+)\\)`));
		return m ? { k: +m[1], n: +m[2], pct: m[3], lo: m[4], hi: m[5] } : null;
	};
	const types = [...text.matchAll(/^\| ([a-z_]+(?: \(clean\): Pass)?) \| (\d+) \| (\d+) \| (\d+)\/(\d+)/gm)].map((m) => ({
		type: LABELS[m[1].replace(" (clean): Pass", "")] || m[1].replace(/_/g, " "), entries: +m[2], strict: +m[4], of: +m[5],
	}));
	return {
		date: runs.at(-1).slice(0, 10),
		version: (text.match(/Starbuck ([\d.]+);/) || [])[1],
		entries: +(text.match(/entries: (\d+)/) || [])[1],
		strict: line("Sensitivity, strict"),
		flagged: line("Sensitivity, flagged"),
		specificity: line("Specificity"),
		types,
	};
}

export default function (eleventyConfig) {
	eleventyConfig.addPassthroughCopy({ "src/assets": "assets" });

	// A short hash of the styles and scripts, appended to their URLs as ?v=, so that
	// Cloudflare or a browser never serves an old copy after a deploy.
	const hash = createHash("sha256");
	for (const dir of ["src/assets/css", "src/assets/js"]) {
		for (const f of fs.readdirSync(path.join(ROOT, dir)).sort()) hash.update(fs.readFileSync(path.join(ROOT, dir, f)));
	}
	eleventyConfig.addGlobalData("assetVersion", hash.digest("hex").slice(0, 10));

	// The version comes from the package, so the site always names the current release.
	const pyproject = fs.readFileSync(path.join(PKG, "pyproject.toml"), "utf8");
	eleventyConfig.addGlobalData("release", { version: (pyproject.match(/^version = "([^"]+)"/m) || [])[1] });
	eleventyConfig.addGlobalData("validation", validation);

	const md = markdownIt({ html: true, typographer: false }).use(markdownItAnchor, {
		level: [2, 3],
		slugify: (s) => eleventyConfig.getFilter("slugify")(s),
		permalink: markdownItAnchor.permalink.headerLink({ safariReaderFix: true }),
	});
	eleventyConfig.setLibrary("md", md);

	// The Changes page shows CHANGELOG.md of the package, without its title line.
	eleventyConfig.addGlobalData("changelogHtml", () => md.render(fs.readFileSync(path.join(PKG, "CHANGELOG.md"), "utf8").replace(/^# .*\n/, "")));

	return {
		dir: { input: "src", output: "_site", includes: "_includes", data: "_data" },
		markdownTemplateEngine: "njk",
		htmlTemplateEngine: "njk",
	};
}
