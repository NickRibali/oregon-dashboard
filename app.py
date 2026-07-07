import streamlit as st
import pandas as pd
import geopandas as gpd
import requests
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Oregon Community Dashboard", layout="wide")

@st.cache_data
def load_data():
    url = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
    gj = requests.get(url, timeout=60).json()
    gj["features"] = [f for f in gj["features"] if f["properties"]["STATE"] == "41"]
    counties = gpd.GeoDataFrame.from_features(gj["features"], crs="EPSG:4326")
    counties["GEOID"] = counties["STATE"] + counties["COUNTY"]

    # population
    pop = pd.read_csv(
        "https://www2.census.gov/programs-surveys/popest/datasets/2020-2023/counties/totals/co-est2023-alldata.csv",
        encoding="latin-1",
    )
    pop = pop[(pop["STATE"] == 41) & (pop["SUMLEV"] == 50)]
    pop["GEOID"] = pop["STATE"].astype(str).str.zfill(2) + pop["COUNTY"].astype(str).str.zfill(3)
    counties = counties.merge(
        pop[["GEOID", "POPESTIMATE2023"]].rename(columns={"POPESTIMATE2023": "population"}),
        on="GEOID", how="left")

    CENSUS_KEY = st.secrets["CENSUS_KEY"]
    inc_url = "https://api.census.gov/data/2022/acs/acs5"
    inc_params = {"get": "NAME,B19013_001E", "for": "county:*", "in": "state:41", "key": CENSUS_KEY}
    idata = requests.get(inc_url, params=inc_params).json()
    income = pd.DataFrame(idata[1:], columns=idata[0])
    income["GEOID"] = income["state"] + income["county"]
    income["income"] = pd.to_numeric(income["B19013_001E"])
    counties = counties.merge(income[["GEOID", "income"]], on="GEOID", how="left")

    # poverty
    pov = pd.read_csv("or_pov_2022_t.csv")
    pov_cty = pov.groupby(["STATEFP", "COUNTYFP"]).agg(
        hh=("TOT_HOUS22", "sum"), below=("TOT_BPOV22", "sum")).reset_index()
    pov_cty["poverty_rate"] = (pov_cty["below"] / pov_cty["hh"] * 100).round(1)
    pov_cty["GEOID"] = pov_cty["STATEFP"].astype(str).str.zfill(2) + pov_cty["COUNTYFP"].astype(str).str.zfill(3)
    counties = counties.merge(pov_cty[["GEOID", "poverty_rate"]], on="GEOID", how="left")

    # unemployment
    def norm(s): return str(s).strip().lower().replace(" county", "")
    unemp = pd.read_csv("oregon_unemployment.csv")
    unemp = unemp[unemp["State"] == "Oregon"]
    unemp = unemp[unemp["Year"] == unemp["Year"].max()]
    unemp = unemp.groupby("County")["Rate"].mean().round(1).reset_index()
    unemp["name_key"] = unemp["County"].apply(norm)
    counties["name_key"] = counties["NAME"].apply(norm)
    counties = counties.merge(
        unemp[["name_key", "Rate"]].rename(columns={"Rate": "unemp_rate"}),
        on="name_key", how="left")

    # churches
    ch = pd.read_csv("oregon_churches.csv")
    churches = gpd.GeoDataFrame(ch, geometry=gpd.points_from_xy(ch.lon, ch.lat), crs="EPSG:4326")
    joined = gpd.sjoin(churches, counties[["GEOID", "geometry"]], how="left", predicate="within")
    counts = joined.groupby("GEOID").size().rename("church_count").reset_index()
    counties = counties.merge(counts, on="GEOID", how="left")
    counties["church_count"] = counties["church_count"].fillna(0).astype(int)
    counties["churches_per_10k"] = (counties["church_count"] / counties["population"] * 10000).round(1)

    return counties

counties = load_data()

# ---------- UI ----------
st.title("Oregon Community Dashboard")
st.markdown("""
This dashboard helps families and community planners compare Oregon's 36 counties
across key indicators. **Use the dropdown** to choose a variable — the map recolors,
the bar chart re-ranks the counties, and you can hover over any county to see all its stats.
Check **"Show underlying data"** at the bottom to view the raw numbers.

*Note: church density is shown per capita and tends to run high in small rural counties;
crime and neighborhood-level detail vary within counties, so treat county averages as a starting point.*
""")

labels = {
    "population": "Population",
    "income": "Median Household Income",
    "poverty_rate": "Poverty Rate (%)",
    "unemp_rate": "Unemployment Rate (%)",
    "churches_per_10k": "Churches per 10k Residents",
}
variable = st.selectbox("Choose a variable:", list(labels.keys()),
                        format_func=lambda k: labels[k])

# ---- MAP ----
m = folium.Map(location=[44.0, -120.5], zoom_start=7, tiles="cartodbpositron")
folium.Choropleth(
    geo_data=counties, data=counties,
    columns=["GEOID", variable], key_on="feature.properties.GEOID",
    fill_color="YlGnBu", fill_opacity=0.7, line_opacity=0.3,
    legend_name=labels[variable],
).add_to(m)
folium.GeoJson(
    counties,
    tooltip=folium.GeoJsonTooltip(
        fields=["NAME", "population", "income", "poverty_rate", "unemp_rate", "churches_per_10k"],
        aliases=["County:", "Population:", "Median Income:", "Poverty %:", "Unemployment %:", "Churches/10k:"],
    ),
).add_to(m)
st_folium(m, width=900, height=550)

# ---- BAR CHART (NEW) ----
st.subheader(f"Counties ranked by {labels[variable]}")
ranked = counties[["NAME", variable]].sort_values(variable, ascending=False).set_index("NAME")
st.bar_chart(ranked)

# ---- DATA TABLE TOGGLE (NEW) ----
if st.checkbox("Show underlying data"):
    st.dataframe(
        counties[["NAME", "population", "income", "poverty_rate", "unemp_rate", "churches_per_10k"]]
        .rename(columns={"NAME": "County", **labels})
    )