// Checks the built site before a deploy:
// - every internal link points to a page that exists, and every #anchor to an id on that page;
// - every page that names a translation (hreflang) names one that exists;
// Exits with 1 on a broken link.

import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = join(import.meta.dirname, "..");
const SITE = process.argv[2] ?? join(ROOT, "_site"); // another build folder may be given

function pages(dir) {
	return readdirSync(dir).flatMap((name) => {
		const p = join(dir, name);
		if (statSync(p).isDirectory()) return pages(p);
		return name.endsWith(".html") ? [p] : [];
	});
}

/** The file that a site path such as /install/ or /install.sh is served from. */
function target(path) {
	const clean = decodeURIComponent(path.split("?")[0]);
	const file = join(SITE, clean);
	if (clean.endsWith("/")) return join(file, "index.html");
	if (existsSync(file) && statSync(file).isFile()) return file;
	return join(file, "index.html");
}

const ids = new Map();
function idsOf(file) {
	if (!ids.has(file)) ids.set(file, new Set([...readFileSync(file, "utf8").matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])));
	return ids.get(file);
}

const problems = [];
for (const file of pages(SITE)) {
	const html = readFileSync(file, "utf8");
	const where = "/" + relative(SITE, file).replace(/index\.html$/, "");
	for (const [, attr, href] of html.matchAll(/\s(href|src)="([^"]+)"/g)) {
		if (href.startsWith("//") || /^[a-z]+:/i.test(href)) continue;
		const [path, hash] = href.split("#");
		const dest = path ? target(path.startsWith("/") ? path : join(where, path)) : file;
		if (!existsSync(dest)) {
			problems.push(`${where}: ${attr} ${href} has no page`);
			continue;
		}
		if (hash && dest.endsWith(".html") && !idsOf(dest).has(hash)) problems.push(`${where}: ${href} has no #${hash}`);
	}
	for (const [, href] of html.matchAll(/<link rel="alternate" hreflang="[^"]+" href="https?:\/\/[^/]+([^"]*)"/g)) {
		if (!existsSync(target(href))) problems.push(`${where}: the translation ${href} does not exist`);
	}
}

if (problems.length) {
	console.error(`${problems.length} broken link(s):\n` + problems.map((p) => `  ${p}`).join("\n"));
	process.exit(1);
}
console.log(`Site check: ${pages(SITE).length} pages, links and anchors ok.`);
