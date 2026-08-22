import js from "@eslint/js";
import globals from "globals";
import pluginVue from "eslint-plugin-vue";
import { defineConfig } from "eslint/config";

export default defineConfig([
  { files: ["**/*.{js,mjs,cjs}"],
    plugins: { js },
    extends: ["js/recommended"],
    languageOptions: {
      globals: {
        ...globals.browser,
        Vue: "readonly",
        AstrBotPluginPage: "readonly"
      }
    },
    rules: {
      "no-unused-vars": [{ "argsIgnorePattern": "^_" }]
    }
  },
  pluginVue.configs["flat/essential"],
]);
