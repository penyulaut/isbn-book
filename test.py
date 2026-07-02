import base64
import os
from datetime import datetime
from threading import Lock

import cv2
import gspread
import numpy as np
import requests
from flask import Flask, jsonify, render_template, request
from gspread.exceptions import WorksheetNotFound
from pyzbar.pyzbar import decode

API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "AIzaSyAOqaDwXsMRWuj5C5OkvdftJNxSJ8c7bv0")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "1EfX9BVSsirrXjZ_B64k-qakUicW1nq61628Gx082gXo")
GOOGLE_SHEETS_WORKSHEET_NAME = os.getenv("GOOGLE_SHEETS_WORKSHEET_NAME", "Books")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "books-recognition-500615-4385e1b0aa91.json")
GOOGLE_SHEETS_HEADERS = [
    "isbn",
    "title",
    "authors",
    "publisher",
    "publishedDate",
    "categories",
    "source",
    "description",
    "cover",
    "savedAt",
]
GOOGLE_SHEETS_LOCK = Lock()

app = Flask(__name__)


def normalize_isbn(isbn):
    return "".join(ch for ch in str(isbn) if ch.isdigit() or ch.upper() == "X")


def decode_barcode_from_image(image_bytes):
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if frame is None:
        return None

    barcodes = decode(frame)
    if len(barcodes) == 0:
        return None

    return barcodes[0].data.decode("utf-8")


def fetch_book_info(isbn):
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&key={API_KEY}"
    response = requests.get(url, timeout=15)
    response.raise_for_status()

    data = response.json()
    if data.get("totalItems", 0) == 0:
        return None

    info = data["items"][0]["volumeInfo"]
    return {
        "title": info.get("title"),
        "authors": ", ".join(info.get("authors", [])),
        "publisher": info.get("publisher"),
        "publishedDate": info.get("publishedDate"),
        "categories": ", ".join(info.get("categories", [])),
        "isbn": isbn,
        "cover": info.get("imageLinks", {}).get("thumbnail"),
        "description": info.get("description", "-"),
    }


def fetch_book_info_perpusnas(isbn):
    normalized_isbn = normalize_isbn(isbn)
    if not normalized_isbn:
        return None

    params = {
        "search": normalized_isbn,
        "filter_by": "code",
        "jenis_media": "all",
        "by_penerbit": "",
        "by_kota": "",
        "draw": "1",
        "start": "0",
        "length": "10",
    }

    response = requests.get(
        "https://isbn.perpusnas.go.id/landing_page/serverside_search2",
        params=params,
        timeout=15,
    )
    response.raise_for_status()

    data = response.json()
    rows = data.get("data", [])
    if not rows:
        return None

    selected_row = None
    for row in rows:
        row_code = normalize_isbn(row.get("code", ""))
        row_isbn = normalize_isbn(row.get("isbn", ""))
        if row_code == normalized_isbn or row_isbn == normalized_isbn:
            selected_row = row
            break

    if selected_row is None:
        selected_row = rows[0]

    return {
        "title": selected_row.get("title") or "-",
        "authors": "-",
        "publisher": selected_row.get("nama_penerbit") or "-",
        "publishedDate": selected_row.get("tahun_terbit") or "-",
        "categories": ", ".join(
            part
            for part in [
                selected_row.get("jenis_media"),
                selected_row.get("jenis_kategori"),
                selected_row.get("tempat_terbit"),
            ]
            if part
        )
        or "-",
        "isbn": selected_row.get("isbn") or selected_row.get("code") or isbn,
        "cover": None,
        "description": "Sumber: Perpusnas RI",
        "source": "perpusnas",
    }


def resolve_book_info(isbn):
    google_book = fetch_book_info(isbn)
    if google_book:
        google_book["source"] = "google_books"
        return google_book

    perpusnas_book = fetch_book_info_perpusnas(isbn)
    if perpusnas_book:
        return perpusnas_book

    return None


def get_google_sheets_client():
    if not GOOGLE_SERVICE_ACCOUNT_FILE:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_FILE belum diset."
        )

    return gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)


def get_google_worksheet():
    if not GOOGLE_SHEETS_SPREADSHEET_ID:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID belum diset.")

    client = get_google_sheets_client()
    spreadsheet = client.open_by_key(GOOGLE_SHEETS_SPREADSHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(GOOGLE_SHEETS_WORKSHEET_NAME)
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=GOOGLE_SHEETS_WORKSHEET_NAME,
            rows=1000,
            cols=len(GOOGLE_SHEETS_HEADERS),
        )

    return worksheet


def ensure_google_sheet_headers(worksheet):
    if worksheet.get_all_values():
        return

    worksheet.append_row(GOOGLE_SHEETS_HEADERS, value_input_option="RAW")

def load_saved_isbns(worksheet):
    ensure_google_sheet_headers(worksheet)

    saved_isbns = set()

    for saved_isbn in worksheet.col_values(1)[1:]:
        normalized_saved_isbn = normalize_isbn(saved_isbn)
        if normalized_saved_isbn:
            saved_isbns.add(normalized_saved_isbn)

    return saved_isbns


def save_book_to_spreadsheet(book):
    if not book:
        return {"saved": False, "duplicate": False, "message": "Tidak ada data buku untuk disimpan."}

    isbn = normalize_isbn(book.get("isbn", ""))
    if not isbn:
        return {"saved": False, "duplicate": False, "message": "ISBN tidak valid untuk disimpan."}

    if not GOOGLE_SHEETS_SPREADSHEET_ID or not GOOGLE_SERVICE_ACCOUNT_FILE:
        return {
            "saved": False,
            "duplicate": False,
            "message": "Google Sheets belum dikonfigurasi. Isi GOOGLE_SHEETS_SPREADSHEET_ID dan GOOGLE_SERVICE_ACCOUNT_FILE.",
        }

    with GOOGLE_SHEETS_LOCK:
        try:
            worksheet = get_google_worksheet()
            saved_isbns = load_saved_isbns(worksheet)

            if isbn in saved_isbns:
                return {
                    "saved": False,
                    "duplicate": True,
                    "message": "ISBN sudah tersimpan di Google Sheets.",
                }

            worksheet.append_row(
                [
                    isbn,
                    book.get("title") or "-",
                    book.get("authors") or "-",
                    book.get("publisher") or "-",
                    book.get("publishedDate") or "-",
                    book.get("categories") or "-",
                    book.get("source") or "-",
                    book.get("description") or "-",
                    book.get("cover") or "-",
                    datetime.now().isoformat(timespec="seconds"),
                ],
                value_input_option="RAW",
            )
        except Exception as exc:
            return {
                "saved": False,
                "duplicate": False,
                "message": f"Gagal menyimpan ke Google Sheets: {exc}",
            }

    return {"saved": True, "duplicate": False, "message": "Buku disimpan ke Google Sheets."}


def build_book_payload(isbn, book):
    save_result = save_book_to_spreadsheet(book)
    return {
        "ok": True,
        "isbn": isbn,
        "book": book,
        "saved": save_result["saved"],
        "duplicate": save_result["duplicate"],
        "saveMessage": save_result["message"],
    }


def build_not_found_payload(isbn):
    return {
        "ok": True,
        "isbn": isbn,
        "book": None,
        "found": False,
        "source": None,
        "message": "ISBN tidak ditemukan di Google Books maupun Perpusnas.",
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image")

    if not image_data:
        return jsonify({"ok": False, "message": "Gambar tidak diterima."}), 400

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(image_data)
    except ValueError:
        return jsonify({"ok": False, "message": "Format gambar tidak valid."}), 400

    isbn = decode_barcode_from_image(image_bytes)
    if not isbn:
        return jsonify({"ok": False, "message": "Barcode tidak ditemukan."}), 404

    try:
        book = resolve_book_info(isbn)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "message": f"Error saat mengambil data buku: {exc}"}), 502

    if not book:
        return jsonify(build_not_found_payload(isbn))

    return jsonify(build_book_payload(isbn, book))


@app.route("/lookup", methods=["POST"])
def lookup():
    payload = request.get_json(silent=True) or {}
    isbn = str(payload.get("isbn", "")).strip()

    if not isbn:
        return jsonify({"ok": False, "message": "ISBN tidak boleh kosong."}), 400

    try:
        book = resolve_book_info(isbn)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "message": f"Error saat mengambil data buku: {exc}"}), 502

    if not book:
        return jsonify(build_not_found_payload(isbn))

    return jsonify(build_book_payload(isbn, book))


if __name__ == "__main__":
    app.run(debug=True)