#!/usr/bin/env node
// Pruebas de archiso/airootfs/etc/polkit-1/rules.d/50-churros-store.rules.
// Solo Node, sin dependencias.
//
// La regla se carga con un `polkit` falso que reproduce el init.js de polkitd
// (addRule, Result) y cada acción se construye como la publica pkexec.c:
// program, command_line y user. No hay detalle `command`: esa clave no existe
// y leerla fue el origen de #152. Se comprueba:
//   - cada llamador real, y que su argv sigue escrito así en el código;
//   - intentos que no deben pasar: argumentos extra, `--opt=valor`, rutas
//     relativas o de otro directorio, otros verbos, otro usuario destino...;
//   - el comportamiento de pkexec antes y después de polkit 127 (realpath);
//   - que la regla no vuelve a leer `command` ni `getDetails` y que es ES5.
//
// Uso: node scripts/test-polkit-rules.js
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..");
const RULE = path.join(ROOT, "archiso/airootfs/etc/polkit-1/rules.d/50-churros-store.rules");

// polkit.Result tal como lo define polkitd (src/polkitbackend/init.js).
const Result = Object.freeze({
    NO: "no",
    YES: "yes",
    AUTH_SELF: "auth_self",
    AUTH_SELF_KEEP: "auth_self_keep",
    AUTH_ADMIN: "auth_admin",
    AUTH_ADMIN_KEEP: "auth_admin_keep",
    NOT_HANDLED: null,
});

const YES = Result.YES;
const KEEP = Result.AUTH_ADMIN_KEEP;
// NOT_HANDLED: la regla no decide y se aplica la política por defecto de
// pkexec (auth_admin: contraseña cada vez).
const DEFAULT = Result.NOT_HANDLED;

const NAMES = new Map([
    [YES, "YES"],
    [KEEP, "AUTH_ADMIN_KEEP"],
    [DEFAULT, "NOT_HANDLED"],
]);
const show = (r) => NAMES.get(r) ?? JSON.stringify(r);

// ------------------------------------------------------------------ carga

function loadRule(source) {
    const rules = [];
    const polkit = {
        Result,
        addRule(fn) {
            rules.push(fn);
        },
        addAdminRule() {},
        log() {},
        spawn() {
            throw new Error("la regla no debe lanzar procesos");
        },
    };
    vm.runInNewContext(source, { polkit }, { filename: RULE });
    if (rules.length !== 1) {
        throw new Error(`se esperaba una regla en ${RULE}, hay ${rules.length}`);
    }
    return rules[0];
}

// Action y Subject con la misma forma que los de init.js.
function makeAction(id, details) {
    const action = { id };
    for (const [key, value] of Object.entries(details)) {
        action["_detail_" + key] = value;
    }
    action.lookup = function (name) {
        return this["_detail_" + name];
    };
    return action;
}

function makeSubject({ user = "ana", groups = ["ana", "wheel"], local = true, active = true } = {}) {
    return {
        user,
        groups,
        local,
        active,
        isInGroup(group) {
            return this.groups.indexOf(group) !== -1;
        },
    };
}

// ----------------------------------------------------------- pkexec falso

// $PATH de una sesión de Arch y ejecutables que existen para la búsqueda.
const PATH_DIRS = ["/usr/local/sbin", "/usr/local/bin", "/usr/bin"];
const EXECUTABLES = new Set([
    "/usr/bin/pacman",
    "/usr/bin/flatpak",
    "/usr/bin/timedatectl",
    "/usr/bin/churros-update-utils",
    "/usr/bin/churros-pkexec",
    "/usr/bin/yay",
    "/usr/bin/paru",
    "/usr/bin/bash",
    "/usr/local/bin/churros-snapshot",
    "/usr/local/bin/churros-theme",
    "/usr/local/bin/churros-write-root-config",
]);

// En Arch /bin, /sbin y /usr/sbin son enlaces a /usr/bin.
function realpath(p, links) {
    if (Object.hasOwn(links, p)) {
        return links[p];
    }
    return p.replace(/^\/(usr\/)?s?bin\//, "/usr/bin/");
}

// Detalles de org.freedesktop.policykit.exec según pkexec.c:
//   - nombre sin "/": primer directorio de $PATH que lo tenga;
//   - ruta relativa con "/": cwd + "/" + ruta, sin normalizar;
//   - argv[0] pasa a ser esa ruta absoluta y command_line es argv unido con
//     espacios;
//   - program es esa misma ruta y, desde polkit 127, su realpath.
function pkexecDetails(argv, { version = 127, user = "root", cwd = "/home/ana", links = {} } = {}) {
    const exec = argv.slice();
    let called = exec[0];
    if (!called.startsWith("/")) {
        if (called.includes("/")) {
            called = `${cwd}/${called}`;
        } else {
            const dir = PATH_DIRS.find((d) => EXECUTABLES.has(`${d}/${called}`));
            if (dir === undefined) {
                throw new Error(`pkexec: no está en $PATH: ${called}`);
            }
            called = `${dir}/${called}`;
        }
        exec[0] = called;
    }
    const program = version >= 127 ? realpath(called, links) : called;
    const commandLine = exec.join(" ");
    return {
        user,
        "user.gecos": user,
        "user.display": user,
        program,
        command_line: commandLine,
        cmdline_short: commandLine,
    };
}

// ------------------------------------------------------------------ casos

const STAMP = "20261006-041530";

// Llamadores reales. `source` es el texto que tiene que seguir apareciendo en
// `file` (sin contar saltos de línea ni sangría): si alguien cambia el argv en
// el código sin tocar la regla, esta prueba lo detecta.
const CALLERS = [
    {
        file: "rust/preferences/src/services/update.rs",
        source: ['"churros-pkexec", "/usr/bin/pacman", "-Syu", "--noconfirm"'],
        argv: ["/usr/bin/pacman", "-Syu", "--noconfirm"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/update.rs",
        source: ['"churros-pkexec", "/usr/bin/flatpak", "update", "-y"'],
        argv: ["/usr/bin/flatpak", "update", "-y"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/update.rs",
        source: ['"churros-pkexec", "/usr/bin/churros-update-utils"]'],
        argv: ["/usr/bin/churros-update-utils"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/update.rs",
        source: ['"churros-pkexec", "/usr/local/bin/churros-snapshot", "list", "--json"'],
        argv: ["/usr/local/bin/churros-snapshot", "list", "--json"],
        expect: YES,
    },
    {
        file: "rust/preferences/src/services/update.rs",
        source: ['"churros-pkexec", "/usr/local/bin/churros-snapshot", "create", "manual"'],
        argv: ["/usr/local/bin/churros-snapshot", "create", "manual"],
        expect: YES,
    },
    {
        file: "rust/preferences/src/services/update.rs",
        source: ['"churros-pkexec", "/usr/local/bin/churros-snapshot", "delete", stamp'],
        argv: ["/usr/local/bin/churros-snapshot", "delete", STAMP],
        expect: KEEP,
    },
    {
        file: "archiso/airootfs/usr/local/bin/churros-update-auto",
        source: ["churros-pkexec /usr/bin/pacman -Syu --noconfirm"],
        argv: ["/usr/bin/pacman", "-Syu", "--noconfirm"],
        expect: KEEP,
    },
    {
        file: "archiso/airootfs/usr/local/bin/churros-update-auto",
        source: ["churros-pkexec /usr/bin/flatpak update -y"],
        argv: ["/usr/bin/flatpak", "update", "-y"],
        expect: KEEP,
    },
    {
        file: "archiso/airootfs/usr/local/bin/churros-update-auto",
        source: ["churros-pkexec /usr/bin/churros-update-utils"],
        argv: ["/usr/bin/churros-update-utils"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/datetime.rs",
        source: ['"churros-pkexec", "/usr/bin/timedatectl", "set-timezone", tz'],
        argv: ["/usr/bin/timedatectl", "set-timezone", "Europe/Madrid"],
        expect: YES,
    },
    {
        file: "rust/preferences/src/services/datetime.rs",
        source: ['"churros-pkexec", "/usr/bin/timedatectl", "set-ntp", flag', 'if enabled { "true" } else { "false" }'],
        argv: ["/usr/bin/timedatectl", "set-ntp", "true"],
        expect: YES,
    },
    {
        file: "rust/preferences/src/services/datetime.rs",
        source: ['"churros-pkexec", "/usr/bin/timedatectl", "set-ntp", flag'],
        argv: ["/usr/bin/timedatectl", "set-ntp", "false"],
        expect: YES,
    },
    {
        file: "rust/preferences/src/services/users.rs",
        source: [
            'const WRITE_ROOT_CONFIG: &str = "/usr/local/bin/churros-write-root-config";',
            'Command::new("churros-pkexec") .arg(WRITE_ROOT_CONFIG)',
            '"greetd-autologin", state',
            'if value { "on" } else { "off" }',
        ],
        argv: ["/usr/local/bin/churros-write-root-config", "greetd-autologin", "on"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/users.rs",
        source: ['"greetd-autologin", state'],
        argv: ["/usr/local/bin/churros-write-root-config", "greetd-autologin", "off"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/users.rs",
        source: ['"lightdm-autologin", state'],
        argv: ["/usr/local/bin/churros-write-root-config", "lightdm-autologin", "on"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/users.rs",
        source: ['"lightdm-autologin", state'],
        argv: ["/usr/local/bin/churros-write-root-config", "lightdm-autologin", "off"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/users.rs",
        source: ['"regreet-wallpaper", wallpaper_path'],
        argv: ["/usr/local/bin/churros-write-root-config", "regreet-wallpaper", "/usr/share/churros/wallpapers/ChurrOS-Mountains.png"],
        expect: KEEP,
    },
    {
        file: "rust/preferences/src/services/users.rs",
        source: ['"regreet-greeting", greeting'],
        argv: ["/usr/local/bin/churros-write-root-config", "regreet-greeting", "Bienvenido a ChurrOS"],
        expect: KEEP,
    },
];

// Intentos que tienen que caer en la política por defecto.
const DENIED = [
    // pacman: solo -Syu --noconfirm, tal cual.
    ["/usr/bin/pacman", "-Sy"],
    ["/usr/bin/pacman", "-Syy"],
    ["/usr/bin/pacman", "-Syu"],
    ["/usr/bin/pacman", "-S", "firefox"],
    ["/usr/bin/pacman", "-S", "--noconfirm", "firefox"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm", "firefox"],
    ["/usr/bin/pacman", "-R", "linux"],
    ["/usr/bin/pacman", "-Rns", "--noconfirm", "linux"],
    ["/usr/bin/pacman", "-Sc"],
    ["/usr/bin/pacman", "-Q"],
    ["/usr/bin/pacman", "-U", "/tmp/x.pkg.tar.zst"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm", "--hookdir=/tmp/hooks"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm", "--hookdir", "/tmp/hooks"],
    ["/usr/bin/pacman", "--config=/tmp/pacman.conf", "-Syu", "--noconfirm"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm", "--dbpath=/tmp/db"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm", "--root=/tmp/r"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm", "--sysroot=/tmp/r"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm", ""],
    ["/usr/bin/pacman", "-Syu", "", "--noconfirm"],
    ["/usr/bin/pacman", "-Syu\t--noconfirm"],
    ["/usr/bin/pacman", "-Syu", "--noconfirm\n"],
    // flatpak: solo update -y.
    ["/usr/bin/flatpak", "run", "org.example.App"],
    ["/usr/bin/flatpak", "run", "--command=sh", "org.example.App"],
    ["/usr/bin/flatpak", "install", "-y", "flathub", "org.example.App"],
    ["/usr/bin/flatpak", "update"],
    ["/usr/bin/flatpak", "update", "-y", "org.example.App"],
    ["/usr/bin/flatpak", "update", "-y", "--installation=evil"],
    ["/usr/bin/flatpak", "--installation=evil", "update", "-y"],
    ["/usr/bin/flatpak", "remote-add", "evil", "https://evil.example/repo"],
    ["/usr/bin/flatpak", "override", "--filesystem=host", "org.example.App"],
    // Ya no están en la lista.
    ["/usr/bin/yay", "-Syu"],
    ["/usr/bin/yay"],
    ["/usr/bin/paru", "-S", "evil-pkg"],
    ["/usr/local/bin/churros-theme"],
    // churros-update-utils: sin argumentos, ni siquiera uno vacío.
    ["/usr/bin/churros-update-utils", "https://evil.example/"],
    ["/usr/bin/churros-update-utils", ""],
    ["/usr/bin/churros-update-utils", "--help"],
    // churros-snapshot: tres argv exactos.
    ["/usr/local/bin/churros-snapshot"],
    ["/usr/local/bin/churros-snapshot", "list"],
    ["/usr/local/bin/churros-snapshot", "list", "--plain"],
    ["/usr/local/bin/churros-snapshot", "list", "--json", "extra"],
    ["/usr/local/bin/churros-snapshot", "create"],
    ["/usr/local/bin/churros-snapshot", "create", "pacman"],
    ["/usr/local/bin/churros-snapshot", "create", "manual", "extra"],
    ["/usr/local/bin/churros-snapshot", "delete"],
    ["/usr/local/bin/churros-snapshot", "delete", "2026"],
    ["/usr/local/bin/churros-snapshot", "delete", "../../etc"],
    ["/usr/local/bin/churros-snapshot", "delete", STAMP, "extra"],
    ["/usr/local/bin/churros-snapshot", "restore", STAMP],
    ["/usr/local/bin/churros-snapshot", "restore", "-d", "/dev/sda", STAMP],
    ["/usr/local/bin/churros-snapshot", "cleanup", "0"],
    ["/usr/local/bin/churros-snapshot", "info", STAMP],
    // timedatectl: zona válida o NTP true/false.
    ["/usr/bin/timedatectl", "set-time", "2020-01-01 00:00:00"],
    ["/usr/bin/timedatectl", "set-local-rtc", "1"],
    ["/usr/bin/timedatectl", "set-timezone"],
    ["/usr/bin/timedatectl", "set-timezone", "../../etc/shadow"],
    ["/usr/bin/timedatectl", "set-timezone", "/etc/shadow"],
    ["/usr/bin/timedatectl", "set-timezone", "Europe/../../x"],
    ["/usr/bin/timedatectl", "set-timezone", ".hidden"],
    ["/usr/bin/timedatectl", "set-timezone", "Europe/Madrid", "--host=evil"],
    ["/usr/bin/timedatectl", "-H", "evil", "set-timezone", "UTC"],
    ["/usr/bin/timedatectl", "set-timezone", "Europe/Madrid", "extra"],
    ["/usr/bin/timedatectl", "set-timezone", "-H"],
    ["/usr/bin/timedatectl", "set-timezone", "A/B/C/D"],
    ["/usr/bin/timedatectl", "set-ntp", "yes"],
    ["/usr/bin/timedatectl", "set-ntp", "true", "false"],
    ["/usr/bin/timedatectl", "status"],
    // churros-write-root-config: operaciones acotadas, nunca un destino libre.
    ["/usr/local/bin/churros-write-root-config", "/etc/greetd/config.toml"],
    ["/usr/local/bin/churros-write-root-config", "/etc/shadow"],
    ["/usr/local/bin/churros-write-root-config"],
    ["/usr/local/bin/churros-write-root-config", "greetd-autologin"],
    ["/usr/local/bin/churros-write-root-config", "greetd-autologin", "yes"],
    ["/usr/local/bin/churros-write-root-config", "greetd-autologin", "on", "root"],
    ["/usr/local/bin/churros-write-root-config", "regreet-wallpaper"],
    ["/usr/local/bin/churros-write-root-config", "regreet-wallpaper", "fondo.png"],
    ["/usr/local/bin/churros-write-root-config", "regreet-greeting"],
    ["/usr/local/bin/churros-write-root-config", "regreet-greeting", ""],
    ["/usr/local/bin/churros-write-root-config", "write", "/etc/sudoers"],
    // Wrappers genéricos y otros programas.
    ["/usr/bin/churros-pkexec", "/usr/bin/pacman", "-Syu", "--noconfirm"],
    ["/usr/bin/bash", "-c", "id"],
    ["/usr/bin/env", "/usr/bin/pacman", "-Syu", "--noconfirm"],
    // Mismo nombre en otro directorio.
    ["/home/ana/bin/churros-snapshot", "list", "--json"],
    ["/tmp/churros-update-utils"],
    ["/usr/local/bin/churros-update-utils"],
    ["/usr/bin/churros-snapshot", "list", "--json"],
    ["/usr/local/bin/timedatectl", "set-ntp", "true"],
];

// --------------------------------------------------------------- ejecución

let failures = 0;
let checks = 0;

function check(label, got, expect) {
    checks += 1;
    if (got !== expect) {
        failures += 1;
        console.error(`  ✗ ${label}: ${show(got)}, se esperaba ${show(expect)}`);
    }
}

function decide(rule, details, { subject = makeSubject(), id = "org.freedesktop.policykit.exec" } = {}) {
    return rule(makeAction(id, details), subject);
}

const source = fs.readFileSync(RULE, "utf8");
const rule = loadRule(source);
const label = (argv) => JSON.stringify(argv);

// 1. Llamadores reales, con pkexec de polkit 124 (program sin realpath) y 127.
const squash = (text) => text.replace(/\s+/g, " ");
for (const caller of CALLERS) {
    const text = squash(fs.readFileSync(path.join(ROOT, caller.file), "utf8"));
    for (const snippet of caller.source) {
        checks += 1;
        if (!text.includes(squash(snippet))) {
            failures += 1;
            console.error(`  ✗ ${caller.file} ya no contiene ${JSON.stringify(snippet)}: ` +
                "actualiza la regla y esta tabla a la vez");
        }
    }
    for (const version of [124, 127]) {
        check(`llamador ${label(caller.argv)} (polkit ${version})`,
            decide(rule, pkexecDetails(caller.argv, { version })), caller.expect);
    }
}

// 2. Nombres desnudos resueltos por $PATH (lo que pasa si el llamador no da la
//    ruta absoluta): mismo resultado mientras $PATH sea el de Arch.
check("pacman por $PATH", decide(rule, pkexecDetails(["pacman", "-Syu", "--noconfirm"])), KEEP);
check("churros-snapshot por $PATH",
    decide(rule, pkexecDetails(["churros-snapshot", "list", "--json"])), YES);
check("más zonas horarias",
    ["UTC", "Etc/GMT+3", "Etc/GMT-14", "America/Argentina/Buenos_Aires", "America/Port-au-Prince"]
        .every((tz) => decide(rule, pkexecDetails(["/usr/bin/timedatectl", "set-timezone", tz])) === YES),
    true);

// 3. Denegados, con las dos versiones de pkexec.
for (const argv of DENIED) {
    for (const version of [124, 127]) {
        check(`denegado ${label(argv)} (polkit ${version})`,
            decide(rule, pkexecDetails(argv, { version })), DEFAULT);
    }
}

// 4. Rutas relativas y enlaces.
check("./churros-snapshot en el home",
    decide(rule, pkexecDetails(["./churros-snapshot", "list", "--json"], { cwd: "/home/ana" })), DEFAULT);
for (const version of [124, 127]) {
    check(`./churros-snapshot desde /usr/local/bin (polkit ${version})`,
        decide(rule, pkexecDetails(["./churros-snapshot", "list", "--json"],
            { cwd: "/usr/local/bin", version })), DEFAULT);
    check(`../../usr/bin/pacman (polkit ${version})`,
        decide(rule, pkexecDetails(["../../usr/bin/pacman", "-Syu", "--noconfirm"],
            { cwd: "/home/ana", version })), DEFAULT);
    check(`/bin/pacman, enlace a /usr/bin (polkit ${version})`,
        decide(rule, pkexecDetails(["/bin/pacman", "-Syu", "--noconfirm"], { version })), DEFAULT);
}
// Un enlace con espacios cuyo nombre imita los argumentos: polkit 127 publica
// el realpath en `program`, pero command_line no empieza por él.
check("enlace '/tmp/x list' -> churros-snapshot",
    decide(rule, pkexecDetails(["/tmp/x list", "--json"],
        { links: { "/tmp/x list": "/usr/local/bin/churros-snapshot" } })), DEFAULT);
check("enlace '/tmp/x' -> churros-snapshot",
    decide(rule, pkexecDetails(["/tmp/x", "list", "--json"],
        { links: { "/tmp/x": "/usr/local/bin/churros-snapshot" } })), DEFAULT);

// 5. Usuario destino distinto de root (pkexec --user).
check("pkexec --user ana",
    decide(rule, pkexecDetails(["/usr/local/bin/churros-snapshot", "list", "--json"], { user: "ana" })),
    DEFAULT);

// 6. Sujeto: fuera de wheel o sesión remota.
const harmless = pkexecDetails(["/usr/local/bin/churros-snapshot", "list", "--json"]);
check("sujeto fuera de wheel",
    decide(rule, harmless, { subject: makeSubject({ groups: ["ana"] }) }), DEFAULT);
check("sujeto no local",
    decide(rule, harmless, { subject: makeSubject({ local: false }) }), DEFAULT);
check("sujeto inactivo pero local",
    decide(rule, harmless, { subject: makeSubject({ active: false }) }), YES);

// 7. Solo la clave antigua `command` (lo que esperaba la regla de #152).
check("solo `command`, sin program/command_line",
    decide(rule, { user: "root", command: "/usr/bin/pacman -Syu --noconfirm" }), DEFAULT);

// 8. Otras acciones.
check("otra acción",
    decide(rule, harmless, { id: "org.freedesktop.systemd1.manage-units" }), DEFAULT);
check("Calamares en el Live (usuario churros)",
    decide(rule, {}, { id: "io.calamares.calamares.pkexec.run", subject: makeSubject({ user: "churros", groups: ["churros", "wheel"] }) }),
    YES);
check("Calamares con otro usuario",
    decide(rule, {}, { id: "io.calamares.calamares.pkexec.run" }), DEFAULT);

// 9. Estático: claves inexistentes y sintaxis ES5 (duktape).
const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
for (const [pattern, why] of [
    [/lookup\(\s*["']command["']\s*\)/, "lee lookup(\"command\"), que pkexec no publica"],
    [/getDetails/, "usa action.getDetails(), que no existe"],
    [/\b(let|const|class)\s/, "usa let/const/class (duktape es ES5)"],
    [/=>/, "usa funciones flecha (duktape es ES5)"],
    [/`/, "usa plantillas `...` (duktape es ES5)"],
]) {
    checks += 1;
    if (pattern.test(code)) {
        failures += 1;
        console.error(`  ✗ la regla ${why}`);
    }
}

if (failures > 0) {
    console.error(`test-polkit-rules: ${failures} de ${checks} comprobaciones fallan`);
    process.exit(1);
}
console.log(`test-polkit-rules: ${checks} comprobaciones OK`);
