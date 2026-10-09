import { defineConfig } from "tsdown";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm"],
  dts: true,
  platform: "neutral",
  exports: {
    // CSS do ConjoLoader (com as máscaras embutidas) sai direto da fonte; os apps importam no globals.css.
    customExports: (exports) => ({
      ...exports,
      "./styles/conjo-loader.css": "./styles/conjo-loader.css",
    }),
  },
});
