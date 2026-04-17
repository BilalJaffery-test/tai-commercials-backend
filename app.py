import os
import requests
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow your frontend to call this backend

# Credentials pulled from Render environment variables (never hardcoded)
TENANT_ID = os.environ.get("TENANT_ID")
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
DATASET_ID = os.environ.get("DATASET_ID")


def get_access_token():
    """Get an OAuth token from Microsoft using our app credentials."""
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://analysis.windows.net/powerbi/api/.default"
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]


def query_dataset(token, dax_query):
    """Run a DAX query against the Power BI dataset."""
    url = f"https://api.powerbi.com/v1.0/myorg/datasets/{DATASET_ID}/executeQueries"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "queries": [{"query": dax_query}],
        "serializerSettings": {"includeNulls": True}
    }
    response = requests.post(url, headers=headers, json=body)
    response.raise_for_status()
    return response.json()


@app.route("/")
def home():
    """Health check — confirms the backend is running."""
    return jsonify({
        "status": "online",
        "message": "TAI Commercials backend is running"
    })


@app.route("/api/test-connection")
def test_connection():
    """Diagnostic endpoint — tests each stage of the PBI connection separately."""
    results = {"stages": {}}

    # Stage 1: Get access token
    try:
        token = get_access_token()
        results["stages"]["1_auth"] = {"success": True, "message": "Token obtained"}
    except Exception as e:
        results["stages"]["1_auth"] = {"success": False, "error": str(e)}
        return jsonify(results), 500

    # Stage 2: List workspaces the app has access to
    try:
        url = "https://api.powerbi.com/v1.0/myorg/groups"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        workspaces = r.json().get("value", [])
        results["stages"]["2_workspaces"] = {
            "success": True,
            "count": len(workspaces),
            "workspaces": [{"id": w["id"], "name": w["name"]} for w in workspaces]
        }
    except requests.HTTPError as e:
        results["stages"]["2_workspaces"] = {
            "success": False,
            "error": str(e),
            "response": e.response.text if e.response else None
        }

    # Stage 3: List datasets the app has access to
    try:
        url = "https://api.powerbi.com/v1.0/myorg/datasets"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        datasets = r.json().get("value", [])
        results["stages"]["3_datasets"] = {
            "success": True,
            "count": len(datasets),
            "datasets": [{"id": d["id"], "name": d["name"]} for d in datasets]
        }
    except requests.HTTPError as e:
        results["stages"]["3_datasets"] = {
            "success": False,
            "error": str(e),
            "response": e.response.text if e.response else None
        }

    return jsonify(results)


@app.route("/api/tai-demand")
def tai_demand():
    """Fetches TAI Demand (Month) = SUM(Ee Revenue Mth) + SUM(Con' Margin Mth)"""
    try:
        token = get_access_token()

        # DAX query to pull the two summed columns
        dax = """
        EVALUATE
        ROW(
            "EeRevenueMth", CALCULATE(SUM('Measures'[Ee Revenue (Mth)])),
            "ConMarginMth", CALCULATE(SUM('Measures'[Con Margin (Mth)]))
        )
        """

        result = query_dataset(token, dax)
        row = result["results"][0]["tables"][0]["rows"][0]

        ee_revenue = row.get("[EeRevenueMth]", 0) or 0
        con_margin = row.get("[ConMarginMth]", 0) or 0
        total = ee_revenue + con_margin

        return jsonify({
            "success": True,
            "tai_demand_mth": total,
            "ee_revenue_mth": ee_revenue,
            "con_margin_mth": con_margin
        })

    except requests.HTTPError as e:
        return jsonify({
            "success": False,
            "error": "API call failed",
            "details": str(e),
            "response": e.response.text if e.response else None
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
