// The Python of this package, run in the browser with Pyodide.  ui.html starts
// this worker when it finds no server behind it, as on GitHub Pages, and sends
// here the requests it would have sent to web.py; web.answer answers them.

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
// Everything web.py imports, fetched from beside this file.
const MODULES = ["__init__", "board", "circle", "codec", "maze", "render", "spanning", "web"];

const python = (async () => {
  const {loadPyodide} = await import(PYODIDE + "pyodide.mjs");
  const pyodide = await loadPyodide();
  const sources = await Promise.all(MODULES.map(async name => {
    const response = await fetch(name + ".py");
    if (!response.ok) throw new Error(`${name}.py: ${response.status}`);
    return response.text();
  }));
  pyodide.FS.mkdirTree("/lib/mazestego");
  MODULES.forEach((name, n) => pyodide.FS.writeFile(`/lib/mazestego/${name}.py`, sources[n]));
  pyodide.runPython("import sys; sys.path.insert(0, '/lib')");
  return pyodide.pyimport("mazestego.web");
})();

// One request at a time: Python runs each to its end, a job included, so the
// only way to cancel one is for the page to stop this worker.
onmessage = async ({data: {id, path, body}}) => {
  try {
    const web = await python;
    const progress = (done, total) => postMessage({id, progress: {done, total}});
    const found = JSON.parse(web.answer(path, body === undefined ? undefined : JSON.stringify(body), progress));
    postMessage("error" in found ? {id, error: found.error} : {id, answer: found});
  } catch (error) {
    postMessage({id, error: "Python could not be loaded in this browser: " + error.message});
  }
};
