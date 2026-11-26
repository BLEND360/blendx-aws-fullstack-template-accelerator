#!/usr/bin/env node
// Validates docs structure before syncing to blendx-living-docs
// Usage: node scripts/validate-docs.mjs
// Exit code 0: all valid
// Exit code 1: validation errors found

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { resolve, join, relative } from 'node:path';

const docsRoot = resolve(process.cwd(), 'docs');
const errors = [];
const warnings = [];

function findMarkdownFiles(dir, relativePath = '') {
  const files = [];
  try {
    const entries = readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const fullPath = join(dir, entry.name);
      const relPath = relativePath ? `${relativePath}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        files.push(...findMarkdownFiles(fullPath, relPath));
      } else if (entry.name.endsWith('.md')) {
        files.push({ path: fullPath, rel: relPath });
      }
    }
  } catch (err) {
    errors.push(`Failed to read directory ${dir}: ${err.message}`);
  }
  return files;
}

function validateDoc(file) {
  let content;
  try {
    content = readFileSync(file.path, 'utf8');
  } catch (err) {
    errors.push(`Cannot read ${file.rel}: ${err.message}`);
    return;
  }

  // Check H1 exists (used for title extraction)
  const h1Match = content.match(/^#+\s+(.+)$/m);
  if (!h1Match) {
    errors.push(`${file.rel}: Missing H1 heading (# Title). Used for title extraction.`);
    return;
  }

  // Check H1 in code blocks (can confuse extraction)
  const codeBlockRegex = /```[\s\S]*?```/g;
  const codeBlocks = content.match(codeBlockRegex) || [];
  for (const block of codeBlocks) {
    if (block.match(/^#\s+/m)) {
      warnings.push(`${file.rel}: Found # syntax in code block. May confuse title extraction.`);
    }
  }

  // Check image references (must be in docs/images/)
  const bodyWithoutCode = content.replace(/```[\s\S]*?```/g, '');
  const imageRefs = bodyWithoutCode.match(/!\[.*?\]\(([^)]+)\)/g) || [];
  for (const ref of imageRefs) {
    const pathMatch = ref.match(/!\[.*?\]\(([^)]+)\)/);
    if (pathMatch) {
      const imgPath = pathMatch[1];
      if (!imgPath.startsWith('./images/') && !imgPath.startsWith('../images/') && !imgPath.startsWith('http')) {
        errors.push(`${file.rel}: Image reference should use './images/' or '../images/'. Found: ${imgPath}`);
      }
    }
  }

  // Check links use relative paths
  const bodyWithoutCode2 = content.replace(/```[\s\S]*?```/g, '');
  const linkRefs = bodyWithoutCode2.match(/\[.*?\]\((?!https?:\/\/)([^)]+)\)/g) || [];
  for (const ref of linkRefs) {
    const pathMatch = ref.match(/\[.*?\]\((?!https?:\/\/)([^)]+)\)/);
    if (pathMatch) {
      const linkPath = pathMatch[1];
      if (!linkPath.startsWith('.') && !linkPath.startsWith('#') && linkPath.includes('/')) {
        warnings.push(`${file.rel}: Link may not be relative. Consider using './' prefix: ${linkPath}`);
      }
    }
  }
}

console.log('Validating docs...\n');

const files = findMarkdownFiles(docsRoot);

if (files.length === 0) {
  console.warn('⚠️  No Markdown files found in docs/');
  process.exit(1);
}

console.log(`Found ${files.length} doc(s)\n`);

for (const file of files) {
  validateDoc(file);
}

// Summary
console.log('─'.repeat(60));
if (errors.length === 0 && warnings.length === 0) {
  console.log('✅ All docs are valid.\n');
  process.exit(0);
}

if (errors.length > 0) {
  console.log(`\n❌ ${errors.length} error(s) found:\n`);
  for (const err of errors) {
    console.log(`  • ${err}`);
  }
}

if (warnings.length > 0) {
  console.log(`\n⚠️  ${warnings.length} warning(s):\n`);
  for (const warn of warnings) {
    console.log(`  • ${warn}`);
  }
}

console.log('\n' + '─'.repeat(60));
console.log('Fix errors before syncing. Warnings are informational.\n');

process.exit(errors.length > 0 ? 1 : 0);
