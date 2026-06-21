const esbuild = require("esbuild");

const watch = process.argv.includes("--watch");

const ctx = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "dist/extension.js",
  external: ["vscode"],          // provided by the VS Code runtime
  format: "cjs",
  platform: "node",
  target: "node18",
  sourcemap: true,
  logLevel: "info",
};

(async () => {
  if (watch) {
    const c = await esbuild.context(ctx);
    await c.watch();
    console.log("[esbuild] watching…");
  } else {
    await esbuild.build(ctx);
    console.log("[esbuild] build complete");
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
