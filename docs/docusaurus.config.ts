import { themes as prismThemes } from "prism-react-renderer";
import type { Config } from "@docusaurus/types";
import type * as Preset from "@docusaurus/preset-classic";

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: "python-whatsapp-bot",
  tagline: "Build WhatsApp bots in Python with the WhatsApp Business Cloud API",
  favicon: "img/favicon.ico",

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Set the production url of your site here
  url: "https://python-whatsapp-bot.radidev.com/",
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: "/",

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: "RadiDev", // Usually your GitHub org/user name.
  projectName: "python-whatsapp-bot", // Usually your repo name.

  onBrokenLinks: "throw",

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },

  presets: [
    [
      "classic",
      {
        docs: {
          sidebarPath: "./sidebars.ts",
          editUrl: "https://github.com/Radi-dev/python-whatsapp-cloud-bot/blob/main/docs/",
        },
        blog: false,
        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    // Replace with your project's social card
    image: "img/python-whatsapp-bot-social-card.jpeg",
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: "python-whatsapp-bot",
      logo: {
        alt: "python-whatsapp-bot logo",
        src: "img/logo.svg",
      },
      items: [
        {
          type: "docSidebar",
          sidebarId: "tutorialSidebar",
          position: "left",
          label: "Docs",
        },
        {
          href: "https://pypi.org/project/python-whatsapp-bot/",
          label: "PyPI",
          position: "right",
        },
        {
          href: "https://github.com/Radi-dev/python-whatsapp-cloud-bot",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Docs",
          items: [
            { label: "Getting started", to: "/docs/intro" },
            { label: "Message handlers", to: "/docs/message-handlers" },
            { label: "Context storage", to: "/docs/context-storage" },
          ],
        },
        {
          title: "Project",
          items: [
            { label: "PyPI", href: "https://pypi.org/project/python-whatsapp-bot/" },
            { label: "GitHub", href: "https://github.com/Radi-dev/python-whatsapp-cloud-bot" },
            { label: "Issues", href: "https://github.com/Radi-dev/python-whatsapp-cloud-bot/issues" },
            { label: "Node.js / TypeScript version", href: "https://github.com/radi-dev/whatsapp-cloud-bot-ts" },
          ],
        },
        {
          title: "WhatsApp",
          items: [
            { label: "Cloud API documentation", href: "https://developers.facebook.com/docs/whatsapp/cloud-api/" },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Radi. MIT licensed. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.oceanicNext,
      darkTheme: prismThemes.oneDark,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
