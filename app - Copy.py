import sqlite3
from typing import List, Optional
from urllib.parse import quote
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastmcp import FastMCP

# -------------------------------------------------------------------
# 1. Database Setup & Seeding
# -------------------------------------------------------------------
DB_NAME = "app.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            city TEXT NOT NULL,
            country TEXT NOT NULL,
            address TEXT NOT NULL,
            phone TEXT NOT NULL,
            latitude REAL,
            longitude REAL
        )
    """)
    
    # Seed sample production data if empty
    cursor.execute("SELECT COUNT(*) FROM places")
    if cursor.fetchone()[0] == 0:
        places_data = [
            ("Grand Hyatt Tokyo", "Hotels", "Tokyo", "Japan", "6-10-3 Roppongi, Minato-ku", "+81 3-4333-1234", 35.6595, 139.7289),
            ("St. Luke's International Hospital", "Hospitals", "Tokyo", "Japan", "9-1 Akashicho, Chuo City", "+81 3-3541-5151", 35.6672, 139.7735),
            ("Shinjuku Station", "Railway Station", "Tokyo", "Japan", "3 Chome Shinjuku, Shinjuku City", "+81 50-2016-1600", 35.6896, 139.7006),
            ("Haneda Airport", "Airport", "Tokyo", "Japan", "Hanedakuko, Ota City", "+81 3-5757-8111", 35.5494, 139.7798),
            ("Traditional Machiya Stay", "Home stay", "Kyoto", "Japan", "Gion-machi, Higashiyama-ku", "+81 75-555-0199", 35.0037, 135.7772),
            ("Aman Tokyo Resort", "Resorts", "Tokyo", "Japan", "1-5-6 Otemachi, Chiyoda-ku", "+81 3-5224-3333", 35.6868, 139.7639),
            ("The Plaza Hotel", "Hotels", "New York", "USA", "768 5th Ave, New York, NY 10019", "+1 212-759-3000", 40.7645, -73.9744),
            ("Mount Sinai Hospital", "Hospitals", "New York", "USA", "1468 Madison Ave, New York", "+1 212-241-6500", 40.7900, -73.9526),
            ("JFK International Airport", "Airport", "New York", "USA", "Queens, NY 11430", "+1 718-244-4444", 40.6413, -73.7781)
        ]
        cursor.executemany("""
            INSERT INTO places (name, category, city, country, address, phone, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, places_data)
        conn.commit()
    conn.close()

init_db()

# -------------------------------------------------------------------
# 2. Helper Functions
# -------------------------------------------------------------------
def build_gmaps_url(address: str, name: str, city: str, country: str) -> str:
    query = f"{name}, {address}, {city}, {country}"
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"

def search_places_db(city: str, country: str, category: Optional[str] = None) -> List[dict]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    query = "SELECT name, category, city, country, address, phone FROM places WHERE LOWER(city) = LOWER(?) AND LOWER(country) = LOWER(?)"
    params = [city.strip(), country.strip()]
    
    if category and category.lower() != "all":
        query += " AND LOWER(category) = LOWER(?)"
        params.append(category.strip())
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        name, cat, cty, cntry, addr, phone = row
        results.append({
            "name": name,
            "category": cat,
            "city": cty,
            "country": cntry,
            "address": addr,
            "phone": phone,
            "gmaps_url": build_gmaps_url(addr, name, cty, cntry)
        })
    return results

# -------------------------------------------------------------------
# 3. Model Context Protocol (MCP) Server Setup
# -------------------------------------------------------------------
mcp = FastMCP("City Explorer MCP")

@mcp.tool()
def find_nearby_places(city: str, country: str, category: str = "All") -> str:
    """
    Search nearby entities like Hotels, Hospitals, Home stay, Resorts, Railway Station, or Airport by City and Country.
    """
    results = search_places_db(city, country, category)
    if not results:
        return f"No records found for '{category}' in {city}, {country}."
    
    output = f"### Results for {city}, {country} ({category}):\n\n"
    for item in results:
        output += f"- **{item['name']}** ({item['category']})\n"
        output += f"  - Address: {item['address']}\n"
        output += f"  - Phone: {item['phone']}\n"
        output += f"  - Google Maps: [Open Maps]({item['gmaps_url']})\n\n"
    return output

# -------------------------------------------------------------------
# 4. FastAPI Setup & Endpoints
# -------------------------------------------------------------------
app = FastAPI(title="Nearby Dashboard API")

@app.get("/api/search")
def api_search(
    city: str = Query(..., description="City name"),
    country: str = Query(..., description="Country name"),
    category: Optional[str] = Query("All", description="Place Category")
):
    return {"data": search_places_db(city, country, category)}

@app.get("/", response_class=HTMLResponse)
def render_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>City Places Finder</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"/>
    </head>
    <body class="bg-gray-100 min-h-screen p-6">
        <div class="max-w-6xl mx-auto bg-white rounded-xl shadow-md p-6">
            <h1 class="text-2xl font-bold mb-6 text-gray-800"><i class="fa-solid me-2 fa-map-location-dot text-indigo-600"></i>Nearby Amenities Dashboard</h1>
            
            <form id="searchForm" class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                <div>
                    <label class="block text-sm font-medium text-gray-700">City</label>
                    <input type="text" id="city" value="Tokyo" required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">Country</label>
                    <input type="text" id="country" value="Japan" required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">Category</label>
                    <select id="category" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border">
                        <option value="All">All Categories</option>
                        <option value="Hotels">Hotels</option>
                        <option value="Hospitals">Hospitals</option>
                        <option value="Home stay">Home stay</option>
                        <option value="Resorts">Resorts</option>
                        <option value="Railway Station">Railway Station</option>
                        <option value="Airport">Airport</option>
                    </select>
                </div>
                <div class="flex items-end">
                    <button type="submit" class="w-full bg-indigo-600 text-white p-2 rounded-md hover:bg-indigo-700 font-semibold">Search</button>
                </div>
            </form>

            <div id="results" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
        </div>

        <script>
            async function fetchData() {
                const city = document.getElementById('city').value;
                const country = document.getElementById('country').value;
                const category = document.getElementById('category').value;
                
                const res = await fetch(`/api/search?city=${encodeURIComponent(city)}&country=${encodeURIComponent(country)}&category=${encodeURIComponent(category)}`);
                const json = await res.json();
                
                const container = document.getElementById('results');
                container.innerHTML = '';

                if (json.data.length === 0) {
                    container.innerHTML = `<div class="col-span-full text-center py-8 text-gray-500">No places found. Try another city/country combination (e.g. Tokyo/Japan, New York/USA).</div>`;
                    return;
                }

                json.data.forEach(item => {
                    const card = document.createElement('div');
                    card.className = 'border rounded-lg p-5 shadow-sm hover:shadow-md transition bg-slate-50 flex flex-col justify-between';
                    card.innerHTML = `
                        <div>
                            <div class="flex justify-between items-start mb-2">
                                <h3 class="font-bold text-lg text-gray-900">${item.name}</h3>
                                <span class="text-xs bg-indigo-100 text-indigo-800 px-2 py-1 rounded-full font-medium">${item.category}</span>
                            </div>
                            <p class="text-sm text-gray-600 mb-2"><i class="fa-solid fa-location-dot text-red-500 mr-2"></i>${item.address}</p>
                            <p class="text-sm text-gray-600 mb-4"><i class="fa-solid fa-phone text-green-600 mr-2"></i>${item.phone}</p>
                        </div>
                        <a href="${item.gmaps_url}" target="_blank" class="inline-flex items-center justify-center w-full bg-emerald-600 text-white text-sm font-medium py-2 px-4 rounded hover:bg-emerald-700">
                            <i class="fa-solid fa-map-pin mr-2"></i> Open in Google Maps
                        </a>
                    `;
                    container.appendChild(card);
                });
            }

            document.getElementById('searchForm').addEventListener('submit', (e) => {
                e.preventDefault();
                fetchData();
            });

            // Initial auto-search on launch
            fetchData();
        </script>
    </body>
    </html>
    """