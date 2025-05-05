import csv
import random
from faker import Faker

fake = Faker()
RECORD_COUNT = 2000
OUTPUT_FILE = "properties_stress_test.csv"
EDGE_CASE_RATE = 0.15
FORCED_DUPLICATE_APN = "0000123456"

# Data configuration
CONDITIONS = ["vacant", "occupied", "renovation", "demolished", ""]
SALE_INSTRUMENTS = ["Grant Deed", "Quitclaim", "Trustee", "Invalid Instrument"]

def generate_apn():
    """Generate clean 10-digit numeric APN"""
    return f"{random.randint(0, 9999999999):010}"

def inject_edge_cases(record):
    """Introduce schema-challenging data"""
    case = random.choice([1, 2, 3, 4, 5])

    if case == 1:  # Non-WA properties
        record.update({
            "address.state": random.choice(["CA", "OR", "XX", "WASHINGTON"]),
            "address.zip": fake.postcode_in_state(state_abbr=random.choice(["CA", "OR"]))
        })

    elif case == 2:  # APN issues
        record["apn"] = random.choice([
            "INVALID",
            "123-AB-456",
            "",
            FORCED_DUPLICATE_APN  # already cleaned
        ])

    elif case == 3:  # Type mismatches
        record.update({
            "sale_info.price": random.choice(["high", "1.5m", "1000000 dollars"]),
            "condition_grade": "excellent"
        })

    elif case == 4:  # Address anomalies
        record.update({
            "address.street": "Invalid Street ###",
            "address.city": "",
            "address.zip": random.choice(["00000", "ABCDE", "98001-99999"])
        })

    elif case == 5:  # Nested structure issues
        record.update({
            "enrichment.nuisance": "yes",
            "enrichment.views": "PANORAMIC"
        })

    return record

def generate_property(is_edge_case):
    base_record = {
        "apn": generate_apn(),
        "address.street": fake.street_address(),
        "address.city": fake.city(),
        "address.state": "WA",
        "address.zip": fake.postcode_in_state(state_abbr="WA"),
        "condition": random.choice(CONDITIONS),
        "sale_info.instrument": random.choice(SALE_INSTRUMENTS),
        "sale_info.reason": fake.sentence(3)[:-1],
        "sale_info.last_sold_date": fake.date_between(start_date="-10y", end_date="today").strftime("%Y-%m-%d"),
        "sale_info.price": random.randint(100000, 2000000),
        "lists": "|".join(random.sample(["pre-foreclosure", "tax-defaulted", "VIP"], random.randint(0,2))),
        "upload_sources": "|".join(random.sample(["Stewart Title", "County", "manual"], random.randint(1,2))),
        "condition_grade": random.randint(0, 5),
        "enrichment.nuisance": random.choice([True, False]),
        "enrichment.environmental": random.choice([True, False]),
        "enrichment.views": random.choice(["Full", "Partial", ""]),
        "original_owner": random.choice([True, False])
    }

    if is_edge_case:
        return inject_edge_cases(base_record)
    return base_record

# Generate dataset
records = []
cleaned_apns = set()
edge_case_count = int(RECORD_COUNT * EDGE_CASE_RATE)
forced_duplicates = 0

for i in range(RECORD_COUNT):
    is_edge = i < edge_case_count
    while True:
        prop = generate_property(is_edge)

        # Clean APN for duplicate check (digits only, padded to 10)
        clean_apn = ''.join(filter(str.isdigit, prop["apn"])).zfill(10)[-10:]

        # Skip empty or malformed APNs
        if not clean_apn.isdigit() or len(clean_apn) != 10:
            continue

        # Avoid accidental duplicates in normal records
        if clean_apn in cleaned_apns and not is_edge:
            continue

        cleaned_apns.add(clean_apn)

        # Update record with cleaned APN
        prop["apn"] = clean_apn

        if clean_apn == FORCED_DUPLICATE_APN:
            forced_duplicates += 1
        break

    records.append(prop)

# Write to CSV
with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)

print(f"""Generated {len(records)} property records:
- WA properties: {len([r for r in records if r["address.state"] == "WA"])}
- Non-WA/Invalid states: {edge_case_count//5}
- Valid APNs: {len(cleaned_apns)}
- Forced APN duplicates: {forced_duplicates}
- Price validation cases: {edge_case_count//5}""")
