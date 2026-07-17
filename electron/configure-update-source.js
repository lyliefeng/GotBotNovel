#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const [owner, repo, apiBase = 'https://gitee.com/api/v5'] = process.argv.slice(2);
const safeName = /^[A-Za-z0-9_.-]+$/;

if (!owner || !safeName.test(owner)) {
  throw new Error('Gitee owner 不能为空，且只能包含字母、数字、点、下划线或连字符');
}
if (!repo || !safeName.test(repo)) {
  throw new Error('Gitee repo 不能为空，且只能包含字母、数字、点、下划线或连字符');
}
if (!apiBase.startsWith('https://')) {
  throw new Error('Gitee API 地址必须使用 HTTPS');
}

const packagePath = path.join(__dirname, 'package.json');
const packageMetadata = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
packageMetadata.gotbotUpdate = {
  giteeApiBase: apiBase.replace(/\/+$/, ''),
  giteeOwner: owner,
  giteeRepo: repo,
};
fs.writeFileSync(packagePath, `${JSON.stringify(packageMetadata, null, 2)}\n`);
console.log(`已配置桌面更新源: ${packageMetadata.gotbotUpdate.giteeOwner}/${packageMetadata.gotbotUpdate.giteeRepo}`);
