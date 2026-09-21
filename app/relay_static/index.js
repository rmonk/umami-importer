fetch("manifest.json")
  .then((r) => r.json())
  .then((entries) => {
    entries.sort((a, b) => b.published_at.localeCompare(a.published_at));
    const list = document.getElementById("list");
    list.textContent = "";

    if (entries.length === 0) {
      list.innerHTML = "<li>Nothing published yet.</li>";
      return;
    }

    for (const entry of entries) {
      const li = document.createElement("li");
      const date = (entry.published_at || "").slice(0, 10);

      const recipeLink = document.createElement("a");
      recipeLink.href = `recipes/${entry.slug}.html`;
      recipeLink.textContent = entry.name || "Untitled recipe";

      li.append(`${date} — `, recipeLink);

      if (entry.source_url) {
        const sourceLink = document.createElement("a");
        sourceLink.href = entry.source_url;
        sourceLink.textContent = "source";
        li.append(" · ", sourceLink);
      }

      list.appendChild(li);
    }
  })
  .catch(() => {
    document.getElementById("list").textContent = "Could not load recipes.";
  });
