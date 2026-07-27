const targets = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const target = targets.find(
  (item) => item.type === "page" && item.url.includes("amazon.com/dp/B00Q7OAN50"),
);
if (!target) throw new Error("Amazon product target not found");

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
const response = new Promise((resolve, reject) => {
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id === 1) resolve(message);
  });
  socket.addEventListener("error", reject, { once: true });
});
socket.send(JSON.stringify({
  id: 1,
  method: "Runtime.evaluate",
  params: {
    returnByValue: true,
    expression: `(() => {
      const selectors = {
        root: '#main-sellersprite-extension',
        ready: '#main-sellersprite-extension #ext-main-box',
        login: '#main-sellersprite-extension .ext-sign-in-container',
        captcha: '#main-sellersprite-extension .robot-card-container',
        input: '#main-sellersprite-extension input[name="field-keywords"]',
        results: '#main-sellersprite-extension .result-number-bar',
        exportMenu: '#main-sellersprite-extension .footer-nex .more-btn',
        export: '[id^="el-popper-container"] button'
      };
      const visible = (element) => {
        if (!element) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0;
      };
      const status = Object.fromEntries(Object.entries(selectors).map(([name, selector]) => {
        const elements = [...document.querySelectorAll(selector)];
        return [name, { count: elements.length, visible: elements.some(visible) }];
      }));
      const exportCandidates = [...document.querySelectorAll('#main-sellersprite-extension *')]
        .filter((element) => /导出|export/i.test((element.textContent || '').trim()))
        .filter(visible)
        .slice(0, 30)
        .map((element) => ({
          tag: element.tagName,
          id: element.id || '',
          class: String(element.className || '').slice(0, 200),
          text: (element.textContent || '').trim().slice(0, 40)
        }));
      return { status, exportCandidates };
    })()`,
  },
}));
const message = await response;
console.log(JSON.stringify(message.result.result.value, null, 2));
socket.close();
