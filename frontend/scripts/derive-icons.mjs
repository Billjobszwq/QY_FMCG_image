/**
 * 由 public/favicon.svg 派生位图图标（apple-touch-icon / manifest / OG）。
 * 运行：npm run icons:derive（依赖 devDependency sharp）。
 * SVG 与 favicon/HedgehogMark 同源；位图仅在此脚本派生，不手改。
 */
import sharp from "sharp";
import { fileURLToPath } from "node:url";

const publicDir = new URL("../public/", import.meta.url);
const svg = fileURLToPath(new URL("favicon.svg", publicDir));

const targets = [
  { file: "apple-touch-icon.png", size: 180 },
  { file: "icon-192.png", size: 192 },
  { file: "icon-512.png", size: 512 },
];

for (const { file, size } of targets) {
  await sharp(svg, { density: 384 })
    .resize(size, size)
    .png()
    .toFile(fileURLToPath(new URL(file, publicDir)));
  console.log(`✓ public/${file} (${size}×${size})`);
}
