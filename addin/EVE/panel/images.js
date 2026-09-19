/* Clipboard files are read only in response to the user's paste or file selection. */
"use strict";
const EveImages = (() => {
  const maxBytes = 1024 * 1024;
  const imageURL = value => typeof value === "string" &&
    /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value) && value.length <= 1400000;
  function pasteFiles(clipboard) {
    if (!clipboard) return [];
    const items = Array.from(clipboard.items || []);
    const files = items.filter(item => item.kind === "file" && item.type.startsWith("image/"))
      .map(item => item.getAsFile()).filter(Boolean);
    return files.length ? files : Array.from(clipboard.files || []).filter(file => file.type.startsWith("image/"));
  }
  function read(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("Could not read that image. Try Attach images."));
      reader.onabort = () => reject(new Error("Image loading was cancelled."));
      reader.readAsDataURL(file);
    });
  }
  async function prepare(file) {
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) throw new Error("Choose a PNG, JPEG, or WebP image.");
    if (file.size > 20 * 1024 * 1024) throw new Error("Choose an image smaller than 20 MiB.");
    const source = await read(file);
    const img = await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("That image could not be decoded. Choose another image."));
      image.src = source;
    });
    if (!img.naturalWidth || !img.naturalHeight || img.naturalWidth * img.naturalHeight > 40000000)
      throw new Error("Choose an image with no more than 40 megapixels.");
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 2048 / Math.max(img.naturalWidth, img.naturalHeight));
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Image preparation is unavailable. Reopen EVE and try again.");
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    let url = canvas.toDataURL("image/png");
    const fits = value => value.length - value.indexOf(",") - 1 <= 4 * Math.ceil(maxBytes / 3);
    let compressed = scale < 1;
    if (!fits(url)) {
      compressed = true;
      for (const quality of [0.9, 0.75, 0.6]) {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        url = canvas.toDataURL("image/jpeg", quality);
        if (fits(url)) break;
      }
    }
    if (!fits(url) || !imageURL(url)) throw new Error("This image is still too large. Crop it and paste it again.");
    return {name: String(file.name || "Pasted image").slice(0, 120), url, compressed};
  }
  return {pasteFiles, prepare, imageURL};
})();
