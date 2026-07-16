import type { CapacitorConfig } from '@capacitor/cli';

const serverUrl = process.env.GOTBOT_SERVER_URL?.trim();

const config: CapacitorConfig = {
  appId: 'com.lyuliefeng.gotbotnovel',
  appName: 'GotBotNovel',
  webDir: 'www',
  bundledWebRuntime: false,
};

if (serverUrl) {
  config.server = {
    url: serverUrl,
    cleartext: serverUrl.startsWith('http://'),
  };
}

export default config;
