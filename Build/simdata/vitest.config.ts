import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/**/*.test.ts", "test/**/*.test.ts"],
    globals: false,
    reporters: ["default"],
    testTimeout: 10_000,
  },
});
