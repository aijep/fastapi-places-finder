import sqlite3
import asyncio
import hashlib
from typing import List, Optional
from urllib.parse import quote
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

DB_NAME = "app.db"

# -------------------------------------------------------------------
# 1. Database Initialization
# -------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            country TEXT NOT NULL,
            address TEXT NOT NULL,
            phone TEXT NOT NULL,
            image_url TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def build_gmaps_url(address: str, name: str, city: str, state: str, country: str) -> str:
    query = f"{name}, {address}, {city}, {state}, {country}"
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"

def generate_unique_thumbnail(name: str) -> str:
    initials = "".join([w[0] for w in name.split()[:2]]).upper() or "P"
    color_hex = hashlib.md5(name.encode()).hexdigest()[:6]
    svg_data = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'>"
        f"<rect width='100%' height='100%' fill='%23{color_hex}'/>"
        f"<circle cx='50' cy='50' r='30' fill='white' opacity='0.2'/>"
        f"<text x='50%' y='55%' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='32' font-weight='bold' fill='white'>{initials}</text>"
        f"</svg>"
    )
    return f"data:image/svg+xml;utf8,{quote(svg_data)}"

# -------------------------------------------------------------------
# 2. Extraction Engine
# -------------------------------------------------------------------
async def fetch_places_fast(city: str, state: str, country: str, category: str):
    headers = {"User-Agent": "FastCityExplorer/5.0"}
    search_query = f"{category} in {city} {state} {country}"
    
    extracted_items = []

    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            nom_url = f"https://nominatim.openstreetmap.org/search?q={quote(search_query)}&format=json&extratags=1&limit=15"
            res = await client.get(nom_url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                for item in data:
                    name = item.get("display_name", "").split(",")[0]
                    if name:
                        addr = ", ".join(item.get("display_name", "").split(",")[1:4]) or f"Near {city}"
                        extratags = item.get("extratags", {}) or {}
                        
                        phone = (
                            extratags.get("phone") 
                            or extratags.get("contact:phone") 
                            or extratags.get("contact:mobile") 
                            or "Not Available"
                        )
                        
                        img = extratags.get("image") or extratags.get("wikimedia_commons")
                        if img and not img.startswith("http"):
                            img = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(img)}"
                        
                        lat = float(item.get("lat", 0))
                        lon = float(item.get("lon", 0))
                        
                        if not img:
                            img = generate_unique_thumbnail(name)

                        extracted_items.append({
                            "name": name,
                            "address": addr,
                            "phone": phone,
                            "image_url": img,
                            "lat": lat,
                            "lon": lon
                        })
        except Exception as e:
            print(f"Lookup error: {e}")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for item in extracted_items:
        cursor.execute("SELECT id FROM places WHERE LOWER(name) = LOWER(?) AND LOWER(city) = LOWER(?)", (item["name"], city))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO places (name, category, city, state, country, address, phone, image_url, latitude, longitude)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (item["name"], category, city, state, country, item["address"], item["phone"], item["image_url"], item["lat"], item["lon"]))
    conn.commit()
    conn.close()

def search_places_db(city: str, state: str, country: str, category: Optional[str] = None, page: int = 1, limit: int = 10):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    where_clause = "WHERE LOWER(city) = LOWER(?) AND LOWER(state) = LOWER(?)"
    params = [city.strip(), state.strip()]
    
    if category and category.lower() != "all":
        where_clause += " AND LOWER(category) = LOWER(?)"
        params.append(category.strip())

    cursor.execute(f"SELECT COUNT(*) FROM places {where_clause}", params)
    total_count = cursor.fetchone()[0]

    if total_count < 10:
        asyncio.run(fetch_places_fast(city, state, country, category if category else "Hotels"))
        cursor.execute(f"SELECT COUNT(*) FROM places {where_clause}", params)
        total_count = cursor.fetchone()[0]

    offset = (page - 1) * limit
    cursor.execute(f"SELECT name, category, city, state, country, address, phone, image_url, latitude, longitude FROM places {where_clause} LIMIT ? OFFSET ?", params + [limit, offset])
    rows = cursor.fetchall()
    conn.close()

    results = []
    for idx, row in enumerate(rows, start=offset + 1):
        name, cat, cty, st, cntry, addr, phone, img_url, lat, lng = row
        results.append({
            "serial_no": idx,
            "name": name,
            "category": cat,
            "city": cty,
            "state": st,
            "country": cntry,
            "address": addr,
            "phone": phone,
            "image_url": img_url,
            "latitude": lat,
            "longitude": lng,
            "gmaps_url": build_gmaps_url(addr, name, cty, st, cntry)
        })

    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

    return {
        "items": results,
        "page": page,
        "limit": limit,
        "total_count": total_count,
        "total_pages": total_pages
    }

# -------------------------------------------------------------------
# 3. FastAPI Web Dashboard
# -------------------------------------------------------------------
app = FastAPI(title="Instant Places Extractor")

@app.get("/api/search")
def api_search(
    city: str = Query("Nagaon"),
    state: str = Query("Assam"),
    country: str = Query("India"),
    category: Optional[str] = Query("Hotels"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=10, le=50)
):
    return search_places_db(city, state, country, category, page, limit)

@app.get("/", response_class=HTMLResponse)
def render_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fast City Places Finder</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"/>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    </head>
    <body class="bg-gray-100 p-6 min-h-screen">
        <div class="max-w-7xl mx-auto space-y-6">
            <div class="bg-white rounded-xl shadow-md p-6">
                <h1 class="text-2xl font-bold text-gray-800 mb-4 flex items-center">
                    <i class="fa-solid fa-bolt text-amber-500 mr-2"></i>Instant Places Finder
                </h1>
                
                <form id="searchForm" class="grid grid-cols-1 md:grid-cols-5 gap-4">
                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-1">Country</label>
                        <select id="countrySelect" class="w-full p-2 border rounded-md border-gray-300" onchange="loadStates()">
                            <option value="">Loading Countries...</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-1">State</label>
                        <select id="stateSelect" class="w-full p-2 border rounded-md border-gray-300" onchange="loadCities()" disabled>
                            <option value="">Select State</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-1">City</label>
                        <select id="citySelect" class="w-full p-2 border rounded-md border-gray-300" disabled>
                            <option value="">Select City</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-1">Category</label>
                        <select id="categorySelect" class="w-full p-2 border rounded-md border-gray-300">
                            <option value="Hotels">Hotels</option>
                            <option value="Police Station">Police Station</option>
                            <option value="Fire Station">Fire Station</option>
                            <option value="Hospitals">Hospitals</option>
                            <option value="Railway Station">Railway Station</option>
                            <option value="Airport">Airport</option>
                        </select>
                    </div>
                    <div class="flex items-end">
                        <button type="submit" id="searchBtn" class="w-full bg-indigo-600 text-white p-2 rounded-md font-bold hover:bg-indigo-700">Search</button>
                    </div>
                </form>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div class="lg:col-span-1 space-y-4">
                    <h2 class="text-lg font-bold text-gray-800 flex justify-between items-center">
                        <span>Extracted Places</span>
                        <span id="badgeCount" class="text-xs bg-indigo-100 text-indigo-800 font-bold px-2.5 py-1 rounded-full">0 Found</span>
                    </h2>
                    
                    <div id="results" class="space-y-3 max-h-[580px] overflow-y-auto pr-2"></div>
                    
                    <div class="bg-white p-3 rounded-xl shadow flex justify-between items-center border">
                        <button id="prevBtn" onclick="changePage(-1)" class="bg-indigo-50 text-indigo-700 px-3 py-1.5 rounded-md font-bold hover:bg-indigo-100 disabled:opacity-50">Prev</button>
                        <span id="pageIndicator" class="text-xs font-semibold text-gray-600">Page 1</span>
                        <button id="nextBtn" onclick="changePage(1)" class="bg-indigo-50 text-indigo-700 px-3 py-1.5 rounded-md font-bold hover:bg-indigo-100 disabled:opacity-50">Next</button>
                    </div>
                </div>

                <div class="lg:col-span-2">
                    <div id="map" class="h-[650px] w-full rounded-xl border sticky top-6 shadow-md z-0"></div>
                </div>
            </div>
        </div>

        <!-- Image Zoom Modal -->
        <div id="imageModal" class="fixed inset-0 bg-black bg-opacity-80 hidden z-50 flex items-center justify-center p-4" onclick="closeModal()">
            <div class="relative max-w-4xl max-h-[90vh] bg-white p-2 rounded-lg shadow-2xl" onclick="event.stopPropagation()">
                <button onclick="closeModal()" class="absolute -top-4 -right-4 bg-red-600 text-white rounded-full w-8 h-8 font-bold text-lg shadow">&times;</button>
                <img id="modalImg" src="" alt="Zoomed View" class="max-h-[80vh] w-auto max-w-full rounded object-contain mx-auto">
                <p id="modalCaption" class="text-center text-sm font-semibold text-gray-700 mt-2"></p>
            </div>
        </div>

        <script>
            let currentPage = 1;
            let totalPages = 1;

            let map = L.map('map').setView([26.3452, 92.6835], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
            let markersMap = {}; 
            let activeMarker = null;

            // Helper to generate SVG map pin icons (Blue or Red)
            function createCustomPin(color) {
                const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 36" width="30" height="42">
                    <path fill="${color}" stroke="#FFFFFF" stroke-width="1.5" d="M12 0C5.37 0 0 5.37 0 12c0 9 12 24 12 24s12-15 12-24c0-6.63-5.37-12-12-12z"/>
                    <circle cx="12" cy="12" r="4" fill="#FFFFFF"/>
                </svg>`;
                return L.icon({
                    iconUrl: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg),
                    iconSize: [30, 42],
                    iconAnchor: [15, 42],
                    popupAnchor: [0, -36]
                });
            }

            const blueIcon = createCustomPin('#2563EB');
            const redIcon = createCustomPin('#DC2626');

            function openModal(imgSrc, title) {
                document.getElementById('modalImg').src = imgSrc;
                document.getElementById('modalCaption').innerText = title;
                document.getElementById('imageModal').classList.remove('hidden');
            }

            function closeModal() {
                document.getElementById('imageModal').classList.add('hidden');
            }

            function highlightPlace(idx, lat, lng) {
                if (activeMarker) {
                    activeMarker.setIcon(blueIcon);
                }

                const marker = markersMap[idx];
                if (marker) {
                    marker.setIcon(redIcon);
                    activeMarker = marker;
                    map.flyTo([lat, lng], 16, { duration: 1.2 });
                    marker.openPopup();
                }
            }

            async function loadCountries() {
                const countrySelect = document.getElementById('countrySelect');
                try {
                    const res = await fetch("https://countriesnow.space/api/v0.1/countries/positions");
                    const data = await res.json();
                    countrySelect.innerHTML = '<option value="">Select Country</option>';
                    
                    data.data.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c.name;
                        opt.innerText = c.name;
                        if(c.name === "India") opt.selected = true;
                        countrySelect.appendChild(opt);
                    });
                    await loadStates();
                } catch(e) {
                    countrySelect.innerHTML = '<option value="India" selected>India</option>';
                    await loadStates();
                }
            }

            async function loadStates() {
                const country = document.getElementById('countrySelect').value;
                const stateSelect = document.getElementById('stateSelect');
                stateSelect.innerHTML = '<option value="">Loading States...</option>';
                stateSelect.disabled = true;

                if(!country) return;

                try {
                    const res = await fetch("https://countriesnow.space/api/v0.1/countries/states", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ country })
                    });
                    const data = await res.json();
                    stateSelect.innerHTML = '<option value="">Select State</option>';
                    
                    if(data.data && data.data.states && data.data.states.length > 0) {
                        data.data.states.forEach(s => {
                            const opt = document.createElement('option');
                            opt.value = s.name;
                            opt.innerText = s.name;
                            if(s.name === "Assam") opt.selected = true;
                            stateSelect.appendChild(opt);
                        });
                        stateSelect.disabled = false;
                        await loadCities();
                    } else {
                        stateSelect.innerHTML = '<option value="Assam" selected>Assam</option>';
                        stateSelect.disabled = false;
                        await loadCities();
                    }
                } catch(e) {
                    stateSelect.innerHTML = '<option value="Assam" selected>Assam</option>';
                    stateSelect.disabled = false;
                    await loadCities();
                }
            }

            async function loadCities() {
                const country = document.getElementById('countrySelect').value;
                const state = document.getElementById('stateSelect').value;
                const citySelect = document.getElementById('citySelect');
                citySelect.innerHTML = '<option value="">Loading Cities...</option>';
                citySelect.disabled = true;

                if(!country || !state) return;

                try {
                    const res = await fetch("https://countriesnow.space/api/v0.1/countries/state/cities", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ country, state })
                    });
                    const data = await res.json();
                    citySelect.innerHTML = '<option value="">Select City</option>';
                    
                    if(data.data && data.data.length > 0) {
                        data.data.forEach(city => {
                            const opt = document.createElement('option');
                            opt.value = city;
                            opt.innerText = city;
                            if(city === "Nagaon") opt.selected = true;
                            citySelect.appendChild(opt);
                        });
                        citySelect.disabled = false;
                    } else {
                        citySelect.innerHTML = '<option value="Nagaon" selected>Nagaon</option>';
                        citySelect.disabled = false;
                    }
                } catch(e) {
                    citySelect.innerHTML = '<option value="Nagaon" selected>Nagaon</option>';
                    citySelect.disabled = false;
                }
            }

            async function fetchData(page = 1) {
                currentPage = page;
                const country = document.getElementById('countrySelect').value || "India";
                const state = document.getElementById('stateSelect').value || "Assam";
                const city = document.getElementById('citySelect').value || "Nagaon";
                const category = document.getElementById('categorySelect').value;

                document.getElementById('results').innerHTML = `<div class="p-6 text-center text-indigo-600 bg-white rounded-lg shadow font-semibold"><i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Loading locations...</div>`;

                try {
                    const url = `/api/search?city=${encodeURIComponent(city)}&state=${encodeURIComponent(state)}&country=${encodeURIComponent(country)}&category=${encodeURIComponent(category)}&page=${currentPage}&limit=10`;
                    const res = await fetch(url);
                    const data = await res.json();
                    
                    totalPages = data.total_pages;
                    const container = document.getElementById('results');
                    container.innerHTML = '';
                    
                    // Clear existing markers
                    Object.values(markersMap).forEach(m => map.removeLayer(m));
                    markersMap = {};
                    activeMarker = null;

                    document.getElementById('badgeCount').innerText = `${data.total_count} Found`;

                    let bounds = [];
                    data.items.forEach(item => {
                        const card = document.createElement('div');
                        card.className = 'border rounded-lg p-3 bg-white shadow-sm hover:border-indigo-500 transition cursor-pointer flex gap-3 items-start hover:shadow-md';
                        card.onclick = () => {
                            if (item.latitude && item.longitude) {
                                highlightPlace(item.serial_no, item.latitude, item.longitude);
                            }
                        };

                        card.innerHTML = `
                            <div class="relative group flex-shrink-0">
                                <img src="${item.image_url}" alt="${item.name}" class="w-20 h-20 object-cover rounded-md border cursor-zoom-in" onclick="event.stopPropagation(); openModal('${item.image_url}', '${item.name}')"/>
                            </div>
                            <div class="flex-1 min-w-0">
                                <h3 class="font-bold text-sm text-gray-900 truncate">${item.serial_no}. ${item.name}</h3>
                                <p class="text-xs text-gray-500 mb-1 line-clamp-2"><i class="fa-solid fa-location-dot text-red-500 mr-1"></i>${item.address}</p>
                                <p class="text-xs text-gray-600 mb-2">
                                    <i class="fa-solid fa-phone text-blue-500 mr-1"></i>
                                    ${item.phone !== 'Not Available' 
                                        ? `<a href="tel:${item.phone}" class="hover:underline font-semibold text-blue-600" onclick="event.stopPropagation()">${item.phone}</a>` 
                                        : `<span class="text-gray-400">Not Available</span>`}
                                </p>
                                <a href="${item.gmaps_url}" target="_blank" onclick="event.stopPropagation()" class="inline-flex items-center text-xs text-emerald-600 font-bold hover:underline">
                                    <i class="fa-solid fa-map-pin mr-1"></i> View on Google Maps
                                </a>
                            </div>
                        `;
                        container.appendChild(card);

                        if (item.latitude && item.longitude && item.latitude !== 0) {
                            const popupContent = `
                                <div class="p-1">
                                    <h4 class="font-bold text-sm text-gray-900">${item.serial_no}. ${item.name}</h4>
                                    <p class="text-xs text-gray-600 mt-1"><i class="fa-solid fa-location-dot text-red-500 mr-1"></i>${item.address}</p>
                                    ${item.phone !== 'Not Available' ? `<p class="text-xs font-semibold text-blue-600 mt-1"><i class="fa-solid fa-phone mr-1"></i>${item.phone}</p>` : ''}
                                </div>
                            `;
                            const marker = L.marker([item.latitude, item.longitude], { icon: blueIcon }).bindPopup(popupContent);
                            marker.addTo(map);
                            markersMap[item.serial_no] = marker;
                            bounds.push([item.latitude, item.longitude]);
                        }
                    });

                    if (bounds.length > 0) map.fitBounds(bounds, { padding: [30, 30] });

                    document.getElementById('pageIndicator').innerText = `Page ${data.page} of ${data.total_pages}`;
                    document.getElementById('prevBtn').disabled = currentPage <= 1;
                    document.getElementById('nextBtn').disabled = currentPage >= totalPages;
                } catch (err) {
                    document.getElementById('results').innerHTML = `<div class="p-4 bg-red-50 text-red-600 rounded-lg text-center text-xs">Failed to fetch place results.</div>`;
                }
            }

            function changePage(step) {
                fetchData(currentPage + step);
            }

            document.getElementById('searchForm').addEventListener('submit', (e) => {
                e.preventDefault();
                fetchData(1);
            });

            loadCountries().then(() => fetchData(1));
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)