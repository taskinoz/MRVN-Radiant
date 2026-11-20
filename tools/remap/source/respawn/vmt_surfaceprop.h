// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include <cctype>
#include <string>
#include <algorithm>
#include <vector>
#include <utility>

namespace Respawn {
// Read KeyValues tokens without treating comments or quoted braces as syntax.
// Backslashes are retained except when escaping a quote.
class VmtTokens {
    const std::string &text;
    std::size_t pos = 0;
public:
    explicit VmtTokens(const std::string &value) : text(value) {
        if (text.size() >= 3 && static_cast<unsigned char>(text[0]) == 0xef &&
            static_cast<unsigned char>(text[1]) == 0xbb && static_cast<unsigned char>(text[2]) == 0xbf)
            pos = 3;
    }
    bool next(std::string &value, bool &structural) {
        for (;;) {
            while (pos < text.size() && std::isspace(static_cast<unsigned char>(text[pos]))) ++pos;
            if (pos + 1 < text.size() && text[pos] == '/' && text[pos + 1] == '/') {
                pos = text.find('\n', pos + 2);
                if (pos == std::string::npos) { pos = text.size(); return false; }
            } else if (pos + 1 < text.size() && text[pos] == '/' && text[pos + 1] == '*') {
                const auto end = text.find("*/", pos + 2);
                if (end == std::string::npos) { pos = text.size(); return false; }
                pos = end + 2;
            } else break;
        }
        if (pos == text.size()) return false;
        value.clear(); structural = false;
        if (text[pos] == '{' || text[pos] == '}') {
            value += text[pos++]; structural = true; return true;
        }
        if (text[pos] == '"') {
            ++pos;
            while (pos < text.size() && text[pos] != '"') {
                if (text[pos] == '\\' && pos + 1 < text.size() && text[pos + 1] == '"') ++pos;
                value += text[pos++];
            }
            if (pos == text.size()) return false;
            ++pos;
        } else {
            while (pos < text.size() && !std::isspace(static_cast<unsigned char>(text[pos])) &&
                   text[pos] != '{' && text[pos] != '}') value += text[pos++];
        }
        return true;
    }
};

inline std::string vmtLower(std::string value) {
    for (char &c : value) c = char(std::tolower(static_cast<unsigned char>(c)));
    return value;
}

struct VmtProperty {
    bool present = false;
    std::string value;
};
struct VmtPropertyInfo {
    bool patch = false;
    std::string include;
    VmtProperty direct, insert, replace;
};

inline bool parseVmtPropertyInfo(const std::string &text, const char *propertyName, VmtPropertyInfo &out) {
    VmtTokens tokens(text);
    std::string key, value, section;
    bool syntax = false;
    if (!tokens.next(key, syntax) || syntax) return false;
    VmtPropertyInfo parsed;
    parsed.patch = vmtLower(key) == "patch";
    if (!tokens.next(value, syntax) || !syntax || value != "{") return false;
    unsigned depth = 1;
    while (depth && tokens.next(key, syntax)) {
        if (syntax) {
            if (key != "}") return false;
            if (depth == 2) section.clear();
            --depth;
            continue;
        }
        const std::string folded = vmtLower(key);
        if (!tokens.next(value, syntax)) return false;
        if (syntax) {
            if (value != "{") return false;
            if (depth == 1) section = folded;
            ++depth;
            if (depth > 64) return false;
            continue;
        }
        if (depth == 1 && folded == "include" && parsed.include.empty()) parsed.include = value;
        if (folded != propertyName) continue;
        VmtProperty *property = nullptr;
        if (depth == 1) property = &parsed.direct;
        else if (depth == 2 && section == "insert") property = &parsed.insert;
        else if (depth == 2 && section == "replace") property = &parsed.replace;
        if (property && !property->present) *property = {true, value};
    }
    if (depth) return false;
    out = std::move(parsed);
    return true;
}

inline bool vmtSurfaceProp(const std::string &text, std::string &result) {
    VmtPropertyInfo info;
    if (!parseVmtPropertyInfo(text, "$surfaceprop", info) || info.patch || !info.direct.present || info.direct.value.empty()) return false;
    result = info.direct.value;
    return true;
}

// Includes name a VFS file under materials/. Reject absolute paths and parent
// traversal; fold case for cycle detection while preserving the VFS lookup case.
inline bool vmtAssetPath(std::string input, const char *extension, std::string &out) {
    std::replace(input.begin(), input.end(), '\\', '/');
    if (input.empty() || input[0] == '/' || input.find(':') != std::string::npos || input.find('\0') != std::string::npos)
        return false;
    std::string path;
    for (std::size_t pos = 0; pos <= input.size();) {
        const auto next = input.find('/', pos);
        const auto part = input.substr(pos, next == std::string::npos ? next : next - pos);
        if (part == "..") return false;
        if (!part.empty() && part != ".") { if (!path.empty()) path += '/'; path += part; }
        if (next == std::string::npos) break;
        pos = next + 1;
    }
    const std::string folded = vmtLower(path);
    if (folded.compare(0, 10, "materials/") != 0 || folded.size() <= 14 ||
        folded.compare(folded.size() - 4, 4, extension) != 0) return false;
    out = path;
    return true;
}

template <typename Loader>
bool resolveVmtProperty(const std::string &path, const char *propertyName, Loader &&load, VmtProperty &result) {
    std::vector<std::string> visited;
    auto resolve = [&](auto &&self, const std::string &input, VmtProperty &property) -> bool {
        std::string normalized;
        if (!vmtAssetPath(input, ".vmt", normalized) || visited.size() >= 16) return false;
        const std::string identity = vmtLower(normalized);
        if (std::find(visited.begin(), visited.end(), identity) != visited.end()) return false;
        visited.push_back(identity);
        std::string text;
        VmtPropertyInfo info;
        if (!load(normalized, text) || !parseVmtPropertyInfo(text, propertyName, info)) return false;
        if (!info.patch) { property = info.direct; return true; }
        if (info.include.empty() || !self(self, info.include, property)) return false;
        // Source SDK patch semantics: insert sets the key, replace needs it to exist.
        if (info.insert.present) property = info.insert;
        if (info.replace.present && property.present) property = info.replace;
        return true;
    };
    VmtProperty resolved;
    if (!resolve(resolve, path, resolved)) return false;
    result = std::move(resolved);
    return true;
}

template <typename Loader>
bool resolveVmtSurfaceProp(const std::string &path, Loader &&load, VmtProperty &result) {
    return resolveVmtProperty(path, "$surfaceprop", std::forward<Loader>(load), result);
}
} // namespace Respawn
