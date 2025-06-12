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
    hh = st.number_input("2. How many households are served?", min_value=1, value=350)
    num_deliveries = st.number_input("3. Annual number of deliveries?", min_value=1, value=12)

    produce_lb = st.number_input("4. Produce lbs per HH?", min_value=0.0, value=float(lbs_per_hh_model[program]['produce']))
    purchased_lb = st.number_input("5. Purchased lbs per HH?", min_value=0.0, value=float(lbs_per_hh_model[program]['purchased']))
    donated_lb = st.number_input("6. Donated lbs per HH?", min_value=0.0, value=float(lbs_per_hh_model[program]['donated']))
    miles = st.number_input("7. Miles per delivery?", min_value=0.0, value=30.0)

    submitted = st.form_submit_button("Calculate & Estimate")

if submitted:
    match = cost_estimates[cost_estimates['PROGRAM'] == program]
    if match.empty:
        produce_cost = DEFAULT_PRODUCE_COST_PER_LB
        purchased_cost = DEFAULT_PURCHASED_COST_PER_LB
    else:
        row = match.iloc[0]
        if program == 'BP':
            purchased_cost = 1.27
            produce_cost = row['estimated_produce_cost_per_lb']
        else:
            produce_cost = row['estimated_produce_cost_per_lb']
            purchased_cost = row['estimated_purchased_cost_per_lb']

    prod_total = produce_lb * hh
    purch_total = purchased_lb * hh
    don_total = donated_lb * hh
    total_lbs = prod_total + purch_total + don_total
    total_annual_lbs = total_lbs * num_deliveries

    base_cost = prod_total * produce_cost + purch_total * purchased_cost + don_total * DONATED_COST
    fixed_cost = total_lbs * FIXED_COST_PER_LB
    transport_cost = total_lbs * miles * TRANSPORT_COST_PER_LB_PER_MILE
    delivery_cost = base_cost + transport_cost
    total_cost = fixed_cost + delivery_cost * num_deliveries

    st.markdown(f"""
### Calculation Completed

#### User Inputs
- Program: {program}
- Households: {hh}
- Deliveries per Year: {num_deliveries}
- Produce: {produce_lb} lbs/HH
- Purchased: {purchased_lb} lbs/HH
- Donated: {donated_lb} lbs/HH
- Distance: {miles} miles

---

#### Calculator Outputs
- Total Weight per Delivery: {total_lbs:.2f} lbs
- Base Food Cost per Delivery: ${base_cost:.2f}
- Annual Fixed Cost (@ {FIXED_COST_PER_LB:.4f}/lb): ${fixed_cost:.2f}
- Transport Cost per Delivery: ${transport_cost:.2f}

---

#### Final Outputs
- Total Annual Cost: ${total_cost:.2f}
- Total Annual Lbs Distributed: {total_annual_lbs:.2f} lbs
- Blended Cost per lb: ${total_cost / total_annual_lbs:.4f}
""", unsafe_allow_html=True)
