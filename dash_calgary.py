# %%
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import pandas as pd
import geopandas as gpd
import polars as pl
import plotly.graph_objects as go
from dash.exceptions import PreventUpdate
import plotly.express as px
import dash_bootstrap_components as dbc

# Reading and manipulating data
calgary = pl.read_csv("calgary_income_by_CT.csv", skip_rows=8)
calgary = calgary.with_columns(
    pl.col('Geography').fill_null(strategy='forward').str.extract(r'(\d+\.\d+)', 1).alias('CTNAME')
)
calgary = calgary.with_columns(
    (pl.col("CTNAME").cumcount() % 3).alias("category")
)

# Correct data selection and manipulation
calgary = calgary.with_columns(pl.arange(0, pl.count()).over("CTNAME").alias("position"))

# Filter and prepare for join
number_of_households = calgary.filter(pl.col("position") == 0).select([
    "CTNAME", "2021"
]).rename({"2021": "number_of_households"})

gross_income = calgary.filter(pl.col("position") == 1).select([
    "CTNAME", "2021"
]).rename({"2021": "median_gross_income"})

income_after_tax = calgary.filter(pl.col("position") == 2).select([
    "CTNAME", "2021"
]).rename({"2021": "median_income_after_tax"})

# Joining data
calgary_combined = number_of_households.join(
    gross_income, on="CTNAME", how="left"
).join(
    income_after_tax, on="CTNAME", how="left"
)

calgary_combined = calgary_combined.with_columns(
    (pl.lit("825") + pl.col('CTNAME')).alias("CTUID")
).to_pandas()

calgary_combined['median_gross_income'] = calgary_combined['median_gross_income'].str.replace('[^\d,-]', '')
calgary_combined['median_gross_income'] = pd.to_numeric(calgary_combined['median_gross_income'].str.replace(',', ''), errors='coerce').fillna(0).astype(int)

# Geodata manipulations
geo_tract = gpd.read_file("shape_census.shp")
calgary_combined = pd.merge(calgary_combined, geo_tract, on='CTUID', how='inner')
gdf = gpd.GeoDataFrame(calgary_combined, geometry='geometry')
gdf = gdf.to_crs(epsg=4326)
gdf = gdf[gdf.is_valid]


def clean_and_convert(value):
    try:
        # Convert to float and format with commas for thousands
        return "{:,.0f}".format(float(value.replace(',', '')))
    except ValueError:
        # Handle the exception for non-numeric values
        return "Invalid Value"
# %%

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Define the clean_and_convert function
def clean_and_convert(value):
    try:
        return "{:,.0f}".format(float(value.replace(',', '')))
    except ValueError:
        return "Invalid Value"
    
initial_min_income = int(gdf['median_gross_income'].quantile(0.25))
initial_max_income = int(gdf['median_gross_income'].quantile(0.75))

dcc.RangeSlider(
    id='income-range-slider',
    min=gdf['median_gross_income'].min(),
    max=gdf['median_gross_income'].max(),
    value=[initial_min_income, initial_max_income],
    # Additional properties for marks, step, etc.
)
# App layout
app.layout = dbc.Container([
   dbc.Row(dbc.Col(html.H1("Calgary Census Tract Income Analysis", style={'textAlign': 'center'}), width=12)),
    dbc.Row(dbc.Col(dcc.Markdown("""
        Use the slider to filter census tracts based on gross household median income.
    """, style={'textAlign': 'center'}))),
    dbc.Row([
        dbc.Col(dcc.RangeSlider(
            id='income-range-slider',
            min=gdf['median_gross_income'].min(),
            max=gdf['median_gross_income'].max(),
            value=[initial_min_income, initial_max_income],
            marks={i: f'${i // 1000}k' for i in range(
                gdf['median_gross_income'].min(),
                gdf['median_gross_income'].max() + 1,
                20000  # Adjust this step based on your data range for better granularity
            )},
            step=1000,
            pushable=10000
        ), width=10),
        dbc.Col(html.Button("Download Data", id="btn_csv"), width=2),
    ]),
    dcc.Download(id="download-dataframe-csv"),
    dcc.Graph(id='income-map', style={'height': '600px'}),  # Set height here
    html.P("Median Gross Income by Census Tract in Calgary", style={'textAlign': 'center'})
], fluid=True)

@app.callback(
    Output('income-map', 'figure'),
    [Input('income-range-slider', 'value')],
)
def update_map(value_range):
    filtered_gdf = gdf[(gdf['median_gross_income'] >= value_range[0]) & 
                       (gdf['median_gross_income'] <= value_range[1])]
    
    fig = px.choropleth_mapbox(
        filtered_gdf,
        geojson=filtered_gdf.geometry.__geo_interface__,
        locations=filtered_gdf.index,
        color="median_gross_income",
        color_continuous_scale=px.colors.sequential.Viridis,
        range_color=value_range,
        mapbox_style="carto-positron",
        zoom=10,
        center={"lat": 51.0447, "lon": -114.0719},
        opacity=0.5,
        labels={'median_gross_income': 'Median Gross Income'}
    )
    fig.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        hovermode='closest',
        mapbox=dict(style='open-street-map', bearing=0, pitch=0)
    )
    fig.update_traces(
        customdata=filtered_gdf['number_of_households'].apply(clean_and_convert),
        hovertemplate="<b>CTUID:</b> %{location}<br>" +
                      "<b>Median Gross Income:</b> $%{z}<br>" +
                      "<b>Number of Households:</b> %{customdata}<br>"
    )
    return fig
# Run the server
if __name__ == '__main__':
    app.run_server(debug=True, port=8050)
# %%
