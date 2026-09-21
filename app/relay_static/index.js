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

      const recipeLink = document.createElement("a");
      recipeLink.href = `recipes/${entry.slug}.html`;
      recipeLink.textContent = entry.name || "Untitled recipe";
      li.appendChild(recipeLink);

      const meta = document.createElement("span");
      meta.className = "entry-meta";
      meta.textContent = (entry.published_at || "").slice(0, 10);

      if (entry.source_url) {
        meta.append(" · ");
        const sourceLink = document.createElement("a");
        sourceLink.href = entry.source_url;
        sourceLink.textContent = "source";
        meta.appendChild(sourceLink);
      }

      li.appendChild(meta);
      list.appendChild(li);
    }
  })
  .catch(() => {
    document.getElementById("list").textContent = "Could not load recipes.";
  });
