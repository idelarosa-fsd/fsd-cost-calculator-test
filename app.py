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
TRANSPORT_COST_PER_LB_PER_MILE = 0.02
DONATED_COST = 0.04

# === Load data and compute cost estimates ===
quarterly_path = 'Final_Quarterly_Data.xlsx'
quarter_df = pd.read_excel(quarterly_path)

lbs_per_hh_model = {
    'AGENCY': {'produce': 16, 'purchased': None, 'donated': None},
    'BP': {'produce': 4, 'purchased': 4, 'donated': 4},
    'MP': {'produce': 16, 'purchased': 5, 'donated': 2},
    'PP': {'produce': 24, 'purchased': 0, 'donated': 0},
    'SP': {'produce': 16, 'purchased': 5, 'donated': 2}
}

program_food_ratios = {}
for prog, values in lbs_per_hh_model.items():
    total = sum(v for v in values.values() if v is not None)
    program_food_ratios[prog] = {
        'produce_ratio': (values['produce'] or 0) / total if total else 0,
        'purchased_ratio': (values['purchased'] or 0) / total if total else 0,
        'donated_ratio': (values['donated'] or 0) / total if total else 0
    }

def apply_ratios(row):
    ratios = program_food_ratios.get(row['PROGRAM'], {'produce_ratio': 0, 'purchased_ratio': 0, 'donated_ratio': 0})
    weight = row['Weight']
    return pd.Series({
        'Estimated_Produce_Weight': weight * ratios['produce_ratio'],
        'Estimated_Purchased_Weight': weight * ratios['purchased_ratio'],
        'Estimated_Donated_Weight': weight * ratios['donated_ratio']
    })

quarter_df = quarter_df[quarter_df['Cost'] > 1]
estimated_weights = quarter_df.apply(apply_ratios, axis=1)
quarter_df[['Estimated_Produce_Weight', 'Estimated_Purchased_Weight', 'Estimated_Donated_Weight']] = estimated_weights

program_agg = quarter_df.groupby('PROGRAM').agg({
    'Cost': 'sum',
    'Weight': 'sum',
    'Estimated_Produce_Weight': 'sum',
    'Estimated_Purchased_Weight': 'sum',
    'Estimated_Donated_Weight': 'sum'
}).reset_index()

results = []
for _, row in program_agg.iterrows():
    prog = row['PROGRAM']
    total_cost = row['Cost']
    total_weight = row['Weight']
    prod_wt = row['Estimated_Produce_Weight']
    purch_wt = row['Estimated_Purchased_Weight']
    don_wt = row['Estimated_Donated_Weight']

    blended_cost = total_cost / total_weight if total_weight else 0
    rprod = prod_wt / total_weight if total_weight else 0
    rpurch = purch_wt / total_weight if total_weight else 0
    rdon = don_wt / total_weight if total_weight else 0

    x = y = None
    if prog != 'BP' and (rprod > 0 and rpurch > 0):
        candidate_ys = [round(v, 3) for v in np.linspace(0.5, 1.2, 71)]
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
        x = None
    elif rprod > 0 and rpurch == 0:
        x = (blended_cost - rdon * DONATED_COST) / rprod
        y = None

    results.append({
        'PROGRAM': prog,
        'estimated_produce_cost_per_lb': x,
        'estimated_purchased_cost_per_lb': y
    })

cost_estimates = pd.DataFrame(results)

# === Calculator UI ===
lbs_per_hh = {
    'AGENCY': {'produce': 0, 'purchased': 0, 'donated': 0},
    'BP': {'produce': 0, 'purchased': 0, 'donated': 0},
    'MP': {'produce': 0, 'purchased': 0, 'donated': 0},
    'PP': {'produce': 0, 'purchased': 0, 'donated': 0},
    'SP': {'produce': 0, 'purchased': 0, 'donated': 0}
}

st.markdown(f"<div style='text-align: center;'><img src='{logo_path}' style='height: 140px; margin-bottom: 20px;'></div>", unsafe_allow_html=True)
st.title("Cost Calculator")

with st.form("calculator_form"):
    program = st.selectbox("1. Which program is this?", list(lbs_per_hh.keys()))
    hh = st.number_input("2. How many households are served?", min_value=1, value=350)
    produce_lb = st.number_input("3. How many lbs of produce per HH?", min_value=0.0, value=0.0)
    purchased_lb = st.number_input("4. How many lbs of purchased per HH?", min_value=0.0, value=0.0)
    donated_lb = st.number_input("5. How many lbs of donated per HH?", min_value=0.0, value=0.0)
    miles = st.number_input("6. How many miles will this delivery travel?", min_value=0.0, value=30.0)

    submitted = st.form_submit_button("Calculate & Estimate")

if submitted:
    match = cost_estimates[cost_estimates['PROGRAM'] == program]
    if match.empty:
        produce_cost = 0
        purchased_cost = 0
    else:
        row = match.iloc[0]
        produce_cost = row['estimated_produce_cost_per_lb'] if pd.notna(row['estimated_produce_cost_per_lb']) else 0
        purchased_cost = 1.27 if program == 'BP' else row['estimated_purchased_cost_per_lb'] if pd.notna(row['estimated_purchased_cost_per_lb']) else 0

    prod_total = produce_lb * hh
    purch_total = purchased_lb * hh
    don_total = donated_lb * hh
    total_lbs = prod_total + purch_total + don_total

    base_cost = prod_total * produce_cost + purch_total * purchased_cost + don_total * DONATED_COST
    fixed_cost = total_lbs * FIXED_COST_PER_LB
    transport_cost = total_lbs * miles * TRANSPORT_COST_PER_LB_PER_MILE
    delivery_cost = base_cost + transport_cost
    total_cost = base_cost + fixed_cost + transport_cost

    prod_cost_hh = produce_lb * produce_cost
    purch_cost_hh = purchased_lb * purchased_cost
    don_cost_hh = donated_lb * DONATED_COST

    st.markdown(f"""
### Calculation Completed

#### <strong>User Inputs</strong>
<p><strong>Program:</strong> {program}</p>
<p><strong>Households:</strong> {hh}</p>
<p><strong>Produce per HH:</strong> {produce_lb}</p>
<p><strong>Purchased per HH:</strong> {purchased_lb}</p>
<p><strong>Donated per HH:</strong> {donated_lb}</p>
<p><strong>Distance:</strong> {miles} miles</p>

---

#### <strong>Calculator Outputs</strong>
<p><strong>Total Weight:</strong> {total_lbs:.2f} lbs</p>
<p><strong>Base Food Cost:</strong> ${base_cost:.2f}</p>
<p><strong>Fixed Cost (@ {FIXED_COST_PER_LB:.4f}/lb):</strong> ${fixed_cost:.2f}</p>
<p><strong>Transport Cost (@ $0.02/lb/mile):</strong> ${transport_cost:.2f}</p>

---

#### <strong>Food Cost Per lb Per HH</strong>
<p><strong>Produce:</strong> {produce_lb} lbs × ${produce_cost:.3f} = ${prod_cost_hh:.2f} per HH</p>
<p><strong>Purchased:</strong> {purchased_lb} lbs × ${purchased_cost:.3f} = ${purch_cost_hh:.2f} per HH</p>
<p><strong>Donated:</strong> {donated_lb} lbs × ${DONATED_COST:.2f} = ${don_cost_hh:.2f} per HH</p>

---

#### <strong>Final Outputs</strong>
<p><strong>Delivery Cost (Food + Transport):</strong> ${delivery_cost:.2f}</p>
<p><strong>Total Cost:</strong> ${total_cost:.2f}</p>
<p><strong>Blended Cost per lb:</strong> ${total_cost / total_lbs:.4f}</p>
""", unsafe_allow_html=True)
