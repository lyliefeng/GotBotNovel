const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('gotbotnovel', {
  appName: 'GotBotNovel',
  platform: process.platform,
});
