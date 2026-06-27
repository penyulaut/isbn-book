const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const startBtn = document.getElementById("startBtn");
const scanBtn = document.getElementById("scanBtn");
const lookupBtn = document.getElementById("lookupBtn");
const isbnInput = document.getElementById("isbnInput");
const cameraSelect = document.getElementById("cameraSelect");
const resultEl = document.getElementById("result");
const statusText = document.getElementById("statusText");
const isbnBadge = document.getElementById("isbnBadge");

let stream = null;
let availableCameras = [];

function stopStream() {
  if (!stream) {
    return;
  }

  stream.getTracks().forEach((track) => track.stop());
  stream = null;
}

async function loadCameras(preferredDeviceId = "") {
  const devices = await navigator.mediaDevices.enumerateDevices();
  availableCameras = devices.filter((device) => device.kind === "videoinput");

  cameraSelect.innerHTML = "";

  if (availableCameras.length === 0) {
    cameraSelect.innerHTML =
      '<option value="">Tidak ada kamera ditemukan</option>';
    cameraSelect.disabled = true;
    return;
  }

  availableCameras.forEach((camera, index) => {
    const option = document.createElement("option");
    option.value = camera.deviceId;
    option.textContent = camera.label || `Kamera ${index + 1}`;
    cameraSelect.appendChild(option);
  });

  if (preferredDeviceId) {
    cameraSelect.value = preferredDeviceId;
  }

  cameraSelect.disabled = false;
}

async function startCamera(deviceId = "") {
  stopStream();

  const constraints = {
    video: deviceId
      ? { deviceId: { exact: deviceId } }
      : { facingMode: "environment" },
    audio: false,
  };

  stream = await navigator.mediaDevices.getUserMedia(constraints);
  video.srcObject = stream;
  scanBtn.disabled = false;
}

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.style.color = isError ? "var(--danger)" : "var(--text)";
}

function renderBook(book) {
  if (!book) {
    resultEl.className = "result-empty";
    resultEl.textContent = "Buku tidak ditemukan.";
    return;
  }

  resultEl.className = "result-grid";
  resultEl.innerHTML = `
    <div class="result-item"><span class="label">Judul</span><div class="value">${book.title || "-"}</div></div>
    <div class="result-item"><span class="label">Penulis</span><div class="value">${book.authors || "-"}</div></div>
    <div class="result-item"><span class="label">Penerbit</span><div class="value">${book.publisher || "-"}</div></div>
    <div class="result-item"><span class="label">Tahun</span><div class="value">${book.publishedDate || "-"}</div></div>
    <div class="result-item"><span class="label">Kategori</span><div class="value">${book.categories || "-"}</div></div>
    <div class="result-item"><span class="label">ISBN-13</span><div class="value">${book.isbn || "-"}</div></div>
    ${book.cover ? `<div class="result-item"><span class="label">Cover Buku</span><img class="cover" src="${book.cover}" alt="Cover buku"></div>` : ""}
    <div class="result-item"><span class="label">Deskripsi</span><div class="value">${book.description || "-"}</div></div>
  `;
}

async function fetchBookByIsbn(isbn) {
  const response = await fetch("/lookup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ isbn }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.message || "Terjadi kesalahan.");
  }

  return data;
}

async function handleBookLookup(isbn) {
  const cleanIsbn = isbn.trim();

  if (!cleanIsbn) {
    setStatus("ISBN tidak boleh kosong.", true);
    return;
  }

  lookupBtn.disabled = true;
  scanBtn.disabled = true;
  setStatus("Mencari data buku...");

  try {
    const data = await fetchBookByIsbn(cleanIsbn);
    isbnBadge.textContent = data.isbn || "ISBN ditemukan";
    setStatus(
      data.book
        ? data.source === "perpusnas"
          ? "Buku ditemukan di Perpusnas."
          : "Buku ditemukan."
        : "ISBN ditemukan, tetapi buku tidak ada di API.",
    );
    renderBook(data.book);
  } catch (error) {
    isbnBadge.textContent = "Gagal lookup";
    setStatus(`Error: ${error.message}`, true);
    resultEl.className = "result-empty";
    resultEl.textContent = error.message;
  } finally {
    lookupBtn.disabled = false;
    scanBtn.disabled = false;
  }
}

lookupBtn.addEventListener("click", async () => {
  await handleBookLookup(isbnInput.value);
});

isbnInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    await handleBookLookup(isbnInput.value);
  }
});

startBtn.addEventListener("click", async () => {
  try {
    await startCamera(cameraSelect.value);

    const activeTrack = stream ? stream.getVideoTracks()[0] : null;
    const activeDeviceId =
      activeTrack?.getSettings?.().deviceId || cameraSelect.value;

    await loadCameras(activeDeviceId);

    setStatus(
      "Kamera aktif. Arahkan barcode ke layar lalu tekan Scan Barcode.",
    );
  } catch (error) {
    setStatus(`Gagal mengakses kamera: ${error.message}`, true);
  }
});

cameraSelect.addEventListener("change", async () => {
  if (!cameraSelect.value) {
    return;
  }

  try {
    await startCamera(cameraSelect.value);
    await loadCameras(cameraSelect.value);
    setStatus("Kamera diganti. Arahkan barcode lalu tekan Scan Barcode.");
  } catch (error) {
    setStatus(`Gagal mengganti kamera: ${error.message}`, true);
  }
});

scanBtn.addEventListener("click", async () => {
  if (!video.videoWidth) {
    setStatus("Kamera belum siap.", true);
    return;
  }

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext("2d");
  context.drawImage(video, 0, 0, canvas.width, canvas.height);

  const image = canvas.toDataURL("image/png");

  scanBtn.disabled = true;
  setStatus("Mendeteksi barcode...");

  try {
    const response = await fetch("/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image }),
    });

    const data = await response.json();

    if (!response.ok) {
      isbnBadge.textContent = "Gagal scan";
      resultEl.className = "result-empty";
      resultEl.textContent = data.message || "Terjadi kesalahan.";
      setStatus(data.message || "Scan gagal.", true);
      return;
    }

    isbnBadge.textContent = data.isbn || "ISBN ditemukan";
    setStatus(
      data.book
        ? data.source === "perpusnas"
          ? "Buku ditemukan di Perpusnas."
          : "Buku ditemukan."
        : "ISBN ditemukan, tetapi buku tidak ada di API.",
    );
    renderBook(data.book);
  } catch (error) {
    setStatus(`Error: ${error.message}`, true);
    resultEl.className = "result-empty";
    resultEl.textContent = "Gagal menghubungi server.";
  } finally {
    scanBtn.disabled = false;
  }
});

window.addEventListener("beforeunload", stopStream);
