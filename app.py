import streamlit as st
import pandas as pd
import numpy as np
import base64

# === Load logo ===
with open("FSD LOGO.png", "rb") as f:
    encoded_image = base64.b64encode(f.read()).decode("utf-8")
logo_path = f"data:image/png;base64,{encoded_image}"

# === Constants ===
FIXED_COST_PER_LB = 13044792 / 17562606
TRANSPORT_COST_PER_LB_PER_MILE = 0.01
DONATED_COST = 0.04

# Default Cost Guardrails
DEFAULT_PURCHASED_COST_PER_LB = 1.00
DEFAULT_PRODUCE_COST_PER_LB = 0.75

# === Load data ===
quarterly_path = 'Final_Quarterly_Data.xlsx'
quarter_df = pd.read_excel(quarterly_path)

lbs_per_hh_model = {
    'AGENCY': {'produce': 16, 'purchased': 5, 'donated': 2},
    'BP': {'produce': 4, 'purchased': 4, 'donated': 4},
    'MP': {'produce': 16, 'purchased': 5, 'donated': 2},
    'PP': {'produce': 24, 'purchased': 0, 'donated': 0},
    'SP': {'produce': 16, 'purchased': 5, 'donated': 2}
}

# === Calculate Food Ratios ===
program_food_ratios = {}
for prog, values in lbs_per_hh_model.items():
    total = sum(v for v in values.values() if v is not None)
    program_food_ratios[prog] = {
        'produce_ratio': (values['produce'] or 0) / total if total else 0,
        'purchased_ratio': (values['purchased'] or 0) / total if total else 0,
        'donated_ratio': (values['donated'] or 0) / total if total else 0
    }

# === Apply ratios to historical data ===
quarter_df = quarter_df[quarter_df['Cost'] > 1]
estimated_weights = quarter_df.apply(
    lambda row: pd.Series({
        'Estimated_Produce_Weight': row['Weight'] * program_food_ratios.get(row['PROGRAM'], {}).get('produce_ratio', 0),
        'Estimated_Purchased_Weight': row['Weight'] * program_food_ratios.get(row['PROGRAM'], {}).get('purchased_ratio', 0),
        'Estimated_Donated_Weight': row['Weight'] * program_food_ratios.get(row['PROGRAM'], {}).get('donated_ratio', 0),
    }),
    axis=1
)
quarter_df = pd.concat([quarter_df, estimated_weights], axis=1)

# === Aggregate by program ===
program_agg = quarter_df.groupby('PROGRAM').agg({
    'Cost': 'sum',
    'Weight': 'sum',
    'Estimated_Produce_Weight': 'sum',
    'Estimated_Purchased_Weight': 'sum',
    'Estimated_Donated_Weight': 'sum'
}).reset_index()

# === Backsolve costs ===
results = []
for _, row in program_agg.iterrows():
    prog = row['PROGRAM']
    total_cost = row['Cost']
    total_weight = row['Weight']
    prod_wt, purch_wt, don_wt = row[['Estimated_Produce_Weight', 'Estimated_Purchased_Weight', 'Estimated_Donated_Weight']]

    blended_cost = total_cost / total_weight if total_weight else 0
    rprod = prod_wt / total_weight if total_weight else 0
    rpurch = purch_wt / total_weight if total_weight else 0
    rdon = don_wt / total_weight if total_weight else 0

    x = y = None
    if prog != 'BP' and (rprod > 0 and rpurch > 0):
        candidate_ys = np.linspace(0.5, 1.2, 71)
        best_error = float('inf')
        for candidate_y in candidate_ys:
            candidate_x = (blended_cost - rpurch * candidate_y - rdon * DONATED_COST) / rprod
            reconstructed = rprod * candidate_x + rpurch * candidate_y + rdon * DONATED_COST
            error = abs(reconstructed - blended_cost)
            if error < best_error:
                best_error = error
                x, y = candidate_x, candidate_y
    elif rpurch > 0 and rprod == 0:
        y = (blended_cost - rdon * DONATED_COST) / rpurch
        y = max(0.5, min(1.2, y))
    elif rprod > 0 and rpurch == 0:
        x = (blended_cost - rdon * DONATED_COST) / rprod

    results.append({
        'PROGRAM': prog,
        'estimated_produce_cost_per_lb': x,
        'estimated_purchased_cost_per_lb': y
    })

cost_estimates = pd.DataFrame(results)

# === Apply Guardrails ===
cost_estimates['estimated_produce_cost_per_lb'] = cost_estimates['estimated_produce_cost_per_lb'].fillna(DEFAULT_PRODUCE_COST_PER_LB)
cost_estimates['estimated_purchased_cost_per_lb'] = cost_estimates['estimated_purchased_cost_per_lb'].fillna(DEFAULT_PURCHASED_COST_PER_LB)

# === Streamlit UI ===
st.markdown(f"<div style='text-align: center;'><img src='{logo_path}' style='height: 140px; margin-bottom: 20px;'></div>", unsafe_allow_html=True)
st.title("Cost Calculator")

with st.form("calculator_form"):
    program = st.selectbox("1. Which program is this?", list(lbs_per_hh_model.keys()))
    hh = st.number_input("2. How many households are served per delivery?", min_value=1, value=350)
    deliveries = st.number_input("3. How many annual deliveries will this program receive?", min_value=1, value=12)

    produce_lb = st.number_input("4. How many lbs of produce per HH?", min_value=0.0, value=float(lbs_per_hh_model[program]['produce']))
    purchased_lb = st.number_input("5. How many lbs of purchased per HH?", min_value=0.0, value=float(lbs_per_hh_model[program]['purchased']))
    donated_lb = st.number_input("6. How many lbs of donated per HH?", min_value=0.0, value=float(lbs_per_hh_model[program]['donated']))
    miles = st.number_input("7. How many miles will this delivery travel?", min_value=0.0, value=30.0)

    submitted = st.form_submit_button("Calculate & Estimate")

if submitted:
    match = cost_estimates[cost_estimates['PROGRAM'] == program]
    agg_row = program_agg[program_agg['PROGRAM'] == program].iloc[0]

    if match.empty:
        produce_cost = DEFAULT_PRODUCE_COST_PER_LB
        purchased_cost = DEFAULT_PURCHASED_COST_PER_LB
    else:
        row = match.iloc[0]
        if program == 'BP':
            purchased_cost = 1.27
            if pd.notna(row['estimated_produce_cost_per_lb']):
                produce_cost = row['estimated_produce_cost_per_lb']
            else:
                blended = agg_row['Cost'] / agg_row['Weight'] if agg_row['Weight'] > 0 else 0
                r = 1 / 3
                produce_cost = (blended - (r * 1.27 + r * DONATED_COST)) / r
        else:
            produce_cost = row['estimated_produce_cost_per_lb']
            purchased_cost = row['estimated_purchased_cost_per_lb']

    prod_total = produce_lb * hh
    purch_total = purchased_lb * hh
    don_total = donated_lb * hh
    total_lbs = prod_total + purch_total + don_total

    base_cost = prod_total * produce_cost + purch_total * purchased_cost + don_total * DONATED_COST
    fixed_cost = total_lbs * FIXED_COST_PER_LB
    transport_cost = total_lbs * miles * TRANSPORT_COST_PER_LB_PER_MILE
    delivery_cost = base_cost + transport_cost
    total_cost = delivery_cost * deliveries + fixed_cost
    total_annual_lbs = total_lbs * deliveries
    blended_annual_cost_per_lb = total_cost / total_annual_lbs if total_annual_lbs else 0

    st.markdown(f"""
### Calculation Completed

#### <strong>User Inputs</strong>
<p><strong>Program:</strong> {program}</p>
<p><strong>Households per Delivery:</strong> {hh}</p>
<p><strong>Deliveries per Year:</strong> {deliveries}</p>
<p><strong>Produce per HH:</strong> {produce_lb}</p>
<p><strong>Purchased per HH:</strong> {purchased_lb}</p>
<p><strong>Donated per HH:</strong> {donated_lb}</p>
<p><strong>Distance:</strong> {miles} miles</p>

---

#### <strong>Calculator Outputs</strong>
<p><strong>Total Weight per Delivery:</strong> {total_lbs:.2f} lbs</p>
<p><strong>Base Food Cost per Delivery:</strong> ${base_cost:.2f}</p>
<p><strong>Annual Fixed (Setup) Cost (@ {FIXED_COST_PER_LB:.4f}/lb):</strong> ${fixed_cost:.2f}</p>
<p><strong>Transport Cost per Delivery (@ $0.01/lb/mile):</strong> ${transport_cost:.2f}</p>

---

#### <strong>Food Cost Per lb Per HH</strong>
<p><strong>Produce:</strong> {produce_lb} lbs × ${produce_cost:.3f} = ${produce_lb * produce_cost:.2f} per HH</p>
<p><strong>Purchased:</strong> {purchased_lb} lbs × ${purchased_cost:.3f} = ${purchased_lb * purchased_cost:.2f} per HH</p>
<p><strong>Donated:</strong> {donated_lb} lbs × ${DONATED_COST:.2f} = ${donated_lb * DONATED_COST:.2f} per HH</p>

---

#### <strong>Final Outputs</strong>
<p><strong>Total Cost per Delivery (Food + Transport):</strong> ${delivery_cost:.2f}</p>
<p><strong>Total Annual Cost:</strong> ${total_cost:.2f}</p>
<p><strong>Total Annual Lbs Distributed:</strong> {total_annual_lbs:.2f} lbs</p>
<p><strong>Blended Annual Cost per lb:</strong> ${blended_annual_cost_per_lb:.4f}</p>
""", unsafe_allow_html=True)
