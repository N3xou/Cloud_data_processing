from gradio_client import Client, handle_file
from tkinter import Tk, filedialog
import matplotlib.pyplot as plt

# ----------------------------
# 1️⃣ Connect to your Space
# ----------------------------
client = Client("iYami/1")

# ----------------------------
# 2️⃣ Select an image
# ----------------------------
Tk().withdraw()
file_path = filedialog.askopenfilename(
    title="Select an image",
    filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp")]
)

if not file_path:
    print("No image selected.")
    exit()

print(f"\n📷 Selected image: {file_path}\n")

# ----------------------------
# 3️⃣ Run prediction
# ----------------------------
result = client.predict(
    img=handle_file(file_path),
    api_name="/predict"
)

# ----------------------------
# 4️⃣ Extract labels and probabilities
# ----------------------------
confidences = result['confidences']  # list of dicts
sorted_preds = sorted(confidences, key=lambda x: x['confidence'], reverse=True)

labels = [item['label'] for item in sorted_preds]
probs = [item['confidence'] for item in sorted_preds]

top_label = result['label']
top_conf = probs[0]

print(f"✅ Top Prediction: {top_label} ({top_conf*100:.2f}%)\n")

print("🔹 All Class Probabilities:")
for label, conf in zip(labels, probs):
    print(f"  {label:10s}: {conf*100:6.2f}%")

# ----------------------------
# 5️⃣ Plot pie chart
# ----------------------------
total_prob = sum(probs)
if total_prob < 1.0:
    probs.append(1.0 - total_prob)  # remaining probability
    labels.append("Remaining 7 classes")

# ----------------------------
# 6️⃣ Plot pie chart with exact probabilities
# ----------------------------
def autopct_exact(pct, all_vals):
    """Display the exact probability if >=0.02%"""
    val = all_vals[autopct_exact.idx]
    autopct_exact.idx += 1
    return f"{val*100:.2f}%" if val >= 0.0002 else ""  # 0.02% threshold

autopct_exact.idx = 0  # initialize index

plt.figure(figsize=(8, 8))
plt.pie(
    probs,
    labels=labels,
    autopct=lambda pct: autopct_exact(pct, probs),
    startangle=140,
    colors=plt.cm.tab10.colors + ("lightgray",),  # "Others" slice is gray
    textprops={'fontsize': 16, 'fontweight': 'bold'}
)
plt.title(f"CIFAR-10 Prediction Probabilities\nTop: {top_label} ({top_conf*100:.2f}%)",
          fontsize=18, fontweight='bold')
plt.show()