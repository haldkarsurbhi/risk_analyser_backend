const fs = require('fs');
const path = require('path');
const readPDF = require('./backend/services/parsers/pdfReader');
const parseTechPack = require('./backend/services/parsers/techpackParserLegacy');

async function run() {
    const uploadDir = path.join(__dirname, 'uploads');
    if (!fs.existsSync(uploadDir)) {
        console.log("Uploads dir not found");
        return;
    }

    const files = fs.readdirSync(uploadDir)
        .filter(f => f.endsWith('.pdf'))
        .map(f => ({ name: f, time: fs.statSync(path.join(uploadDir, f)).mtime.getTime() }))
        .sort((a, b) => b.time - a.time);

    if (files.length === 0) {
        console.log("No PDF files found in uploads/");
        return;
    }

    const latestFile = files[0].name;
    const filePath = path.join(uploadDir, latestFile);
    console.log("Analyzing latest file:", latestFile);

    const logs = [];
    const originalLog = console.log;
    console.log = (...args) => {
        logs.push(args.map(a => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' '));
        originalLog(...args);
    };

    try {
        console.log("Reading PDF...");
        const text = await readPDF(filePath);
        console.log("PDF Text Length:", text.length);
        fs.writeFileSync('manual_debug_text.txt', text);

        console.log("Parsing...");
        const result = parseTechPack(text);

        fs.writeFileSync('debug_result.json', JSON.stringify(result, null, 2));
        fs.writeFileSync('debug_script_logs.txt', logs.join('\n'));

        console.log("Result saved to debug_result.json");
    } catch (e) {
        console.error("Error:", e);
        fs.writeFileSync('debug_error.txt', String(e));
    }
}

run();
