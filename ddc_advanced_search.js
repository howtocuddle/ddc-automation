// Advanced DDC Search Algorithm (JavaScript version)
// No external dependencies - pure JavaScript implementation

class DDCAdvancedSearch {
    constructor() {
        this.data = {};
        this.wordIndex = new Map(); // word -> Set of node_ids
    // Map of normalized notation -> Set of node_ids (multiple nodes can share a notation when
    // different records/variants exist, e.g., T3:--8 and T3:-8 both 'Miscellaneous writings').
    this.notationIndex = new Map();
        this.titleIndex = new Map(); // normalized title -> node_id
        this.synonyms = {
            'computer': ['computing', 'computers', 'data processing', 'electronic data processing'],
            'art': ['arts', 'fine arts', 'visual arts'],
            'math': ['mathematics', 'mathematical'],
            'science': ['sciences', 'scientific'],
            'history': ['historical', 'historic'],
            'literature': ['literary', 'writings'],
            'music': ['musical', 'songs'],
            'language': ['languages', 'linguistic', 'linguistics'],
            'religion': ['religious', 'theology', 'theological'],
            'philosophy': ['philosophical'],
            'geography': ['geographical', 'geographic'],
            'biology': ['biological', 'life sciences'],
            'physics': ['physical'],
            'chemistry': ['chemical'],
            'medicine': ['medical', 'health'],
            'law': ['legal', 'jurisprudence'],
            'education': ['educational', 'teaching'],
            'sociology': ['social', 'society'],
            'psychology': ['psychological'],
            'economics': ['economic', 'economy'],
            'politics': ['political', 'government'],
            'engineering': ['technology', 'technical']
        };
    }

    // Smart query detection - determine if query is a notation or keyword
    detectQueryType(query) {
        // Clean the query
        const cleanQuery = query.trim();
        
        // DDC notation patterns
        const ddcPatterns = [
            /^\d{3}$/,                    // 3-digit main class (e.g., "004", "580")
            /^\d{3}\.\d+$/,              // Decimal notation (e.g., "004.5", "580.75")
            /^\d{1,3}$/,                 // 1-3 digit numbers (e.g., "4", "58")
            /^T\d:\d+/,                  // Table notation (e.g., "T1:01", "T2:73")
            /^\.\d+$/,                   // Table subdivision (e.g., ".01", ".73")
            /^\d{3}-\d{3}$/,             // Range notation (e.g., "004-006")
            /^\d+\.\d*-\d+\.\d*$/,       // Decimal range (e.g., "580.1-580.9")
            /^-\d+$/,                    // Negative notation (e.g., "-015")
            /^\d+[A-Z]$/,                // Letter suffix (e.g., "004A")
        ];
        
        // Check if query matches any DDC notation pattern
        const isNotation = ddcPatterns.some(pattern => pattern.test(cleanQuery));
        
        // Additional heuristics
        if (!isNotation) {
            // Check if it's all digits (likely a notation)
            if (/^\d+$/.test(cleanQuery)) {
                return 'notation';
            }
            
            // Check if it contains periods and digits (likely decimal notation)
            if (/^\d*\.\d*$/.test(cleanQuery) && cleanQuery.includes('.')) {
                return 'notation';
            }
        }
        
        return isNotation ? 'notation' : 'keyword';
    }

    // Enhanced search with smart detection
    searchSmart(query, maxResults = 50) {
        const queryType = this.detectQueryType(query);
        
        if (queryType === 'notation') {
            return this.searchNotation(query, maxResults);
        } else {
            return this.searchKeyword(query, maxResults);
        }
    }

    // Notation-focused search (exact matching priority)
    searchNotation(query, maxResults = 50) {
        if (!query.trim()) return [];
        
        const results = new Map();
        const queryLower = query.toLowerCase().trim();
        
        // 1. Exact notation match (highest priority)
        if (this.notationIndex.has(queryLower)) {
            for (const nodeId of this.notationIndex.get(queryLower)) {
                results.set(nodeId, 1000.0); // Very high score for exact match
            }
        }
        
        // 2. Notation starts with query
        for (const [notation, nodeIds] of this.notationIndex) {
            if (notation.startsWith(queryLower) && notation !== queryLower) {
                const score = 900.0 * (queryLower.length / notation.length);
                for (const nodeId of nodeIds) {
                    results.set(nodeId, Math.max(results.get(nodeId) || 0, score));
                }
            }
        }
        
        // 3. Notation contains query
        for (const [notation, nodeIds] of this.notationIndex) {
            if (notation.includes(queryLower) && !notation.startsWith(queryLower)) {
                const score = 800.0 * (queryLower.length / notation.length);
                for (const nodeId of nodeIds) {
                    results.set(nodeId, Math.max(results.get(nodeId) || 0, score));
                }
            }
        }
        
        // 4. Query contains notation (for partial searches like "58" finding "580")
        for (const [notation, nodeIds] of this.notationIndex) {
            if (queryLower.includes(notation) && notation.length >= 2) {
                const score = 700.0 * (notation.length / queryLower.length);
                for (const nodeId of nodeIds) {
                    results.set(nodeId, Math.max(results.get(nodeId) || 0, score));
                }
            }
        }
        
        return this.formatResults(results, query, maxResults, 'notation');
    }

    // Keyword-focused search (semantic matching priority)
    searchKeyword(query, maxResults = 50) {
        if (!query.trim()) return [];
        
        const queryNormalized = this.normalizeText(query);
        const queryWords = this.extractWords(query);
        const results = new Map();
        
        // 1. Exact title match
        if (this.titleIndex.has(queryNormalized)) {
            const nodeId = this.titleIndex.get(queryNormalized);
            results.set(nodeId, 950.0);
        }
        
        // 2. Title starts with query
        for (const [title, nodeId] of this.titleIndex) {
            if (title.startsWith(queryNormalized)) {
                const score = 850.0 * (queryNormalized.length / title.length);
                results.set(nodeId, Math.max(results.get(nodeId) || 0, score));
            }
        }
        
        // 3. Title contains query
        for (const [title, nodeId] of this.titleIndex) {
            if (title.includes(queryNormalized) && !title.startsWith(queryNormalized)) {
                const score = 750.0 * (queryNormalized.length / title.length);
                results.set(nodeId, Math.max(results.get(nodeId) || 0, score));
            }
        }
        
        // 4. Word matching with scoring
        if (queryWords.length > 0) {
            const wordScores = new Map();
            
            for (const word of queryWords) {
                // Exact word match
                if (this.wordIndex.has(word)) {
                    for (const nodeId of this.wordIndex.get(word)) {
                        const currentScore = wordScores.get(nodeId) || 0;
                        wordScores.set(nodeId, currentScore + (600.0 / queryWords.length));
                    }
                }
                
                // Synonym matching
                for (const [mainTerm, synonymList] of Object.entries(this.synonyms)) {
                    if (synonymList.includes(word) || mainTerm === word) {
                        const termToSearch = mainTerm === word ? mainTerm : word;
                        if (this.wordIndex.has(termToSearch)) {
                            for (const nodeId of this.wordIndex.get(termToSearch)) {
                                const currentScore = wordScores.get(nodeId) || 0;
                                wordScores.set(nodeId, currentScore + (500.0 / queryWords.length));
                            }
                        }
                    }
                }
                
                // Partial word match
                for (const [indexedWord, nodeIds] of this.wordIndex) {
                    if (word !== indexedWord && (word.includes(indexedWord) || indexedWord.includes(word))) {
                        const similarity = word.length / Math.max(indexedWord.length, word.length);
                        if (similarity > 0.6) {
                            for (const nodeId of nodeIds) {
                                const score = 400.0 * similarity / queryWords.length;
                                const currentScore = wordScores.get(nodeId) || 0;
                                wordScores.set(nodeId, currentScore + score);
                            }
                        }
                    }
                }
            }
            
            // Add word scores to results
            for (const [nodeId, score] of wordScores) {
                results.set(nodeId, Math.max(results.get(nodeId) || 0, score));
            }
        }
        
        // 5. Lower priority: notation matches for keywords (in case user searches "004" as keyword)
        if (this.notationIndex.has(query.toLowerCase())) {
            for (const nodeId of this.notationIndex.get(query.toLowerCase())) {
                results.set(nodeId, Math.max(results.get(nodeId) || 0, 300.0));
            }
        }
        
        return this.formatResults(results, query, maxResults, 'keyword');
    }

    // Format results helper
    formatResults(results, query, maxResults, searchType) {
        const finalResults = [];
        
        for (const [nodeId, score] of results) {
            if (score > 50.0) { // Minimum relevance threshold
                const matchType = this.determineMatchType(nodeId, query, score, searchType);
                finalResults.push([nodeId, score, matchType]);
            }
        }
        
        // Sort by score (descending), then by notation length (ascending)
        finalResults.sort((a, b) => {
            if (b[1] !== a[1]) return b[1] - a[1];
            const aNotation = this.data[a[0]]?.notation || '';
            const bNotation = this.data[b[0]]?.notation || '';
            return aNotation.length - bNotation.length;
        });
        
        return finalResults.slice(0, maxResults);
    }

    normalizeText(text) {
        if (!text) return "";
        
        text = text.toLowerCase();
        
        // Remove diacritics (basic version)
        text = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        
        // Replace common variations
        text = text.replace(/&/g, 'and')
                  .replace(/\+/g, 'and')
                  .replace(/\bw\//g, 'with')
                  .replace(/\bw\/o/g, 'without')
                  .replace(/\betc\.?/g, 'etcetera')
                  .replace(/\be\.g\./g, 'for example')
                  .replace(/\bi\.e\./g, 'that is')
                  .replace(/\bvs\.?/g, 'versus')
                  .replace(/\bno\./g, 'number')
                  .replace(/\bco\./g, 'company');
        
        return text;
    }

    extractWords(text) {
        const normalized = this.normalizeText(text);
        const words = normalized.match(/\b[a-z]{3,}\b/g) || [];
        
        const stopWords = new Set([
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
            'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his',
            'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'boy',
            'did', 'use', 'way', 'she', 'oil', 'sit', 'set', 'run', 'say', 'put'
        ]);
        
        return words.filter(word => !stopWords.has(word));
    }

    loadData(metaData) {
        console.log('Building advanced search index...');
        this.data = metaData;
        
        // Build indexes
        for (const [nodeId, entry] of Object.entries(metaData)) {
            // Index notation - check both entry.notation and nodeId itself as notation
                let notation = (entry.notation || '').trim();
                if (!notation && /^\d/.test(nodeId)) {
                    notation = nodeId;
                }
                if (notation) {
                    // Standardize T3A notation formats: replace all double dashes with single dash
                    let standardizedNotation = notation.replace(/--/g, '-');
                    const variants = new Set([standardizedNotation.toLowerCase()]);
                    if (standardizedNotation.toLowerCase() !== notation.toLowerCase()) {
                        variants.add(notation.toLowerCase());
                    }
                    for (const key of variants) {
                        if (!this.notationIndex.has(key)) {
                            this.notationIndex.set(key, new Set());
                        }
                        this.notationIndex.get(key).add(nodeId);
                    }
                }
            
            // Index title
            const title = (entry.pref || entry.prefLabel || entry.title || entry.label || '').trim();
            if (title) {
                const normalizedTitle = this.normalizeText(title);
                this.titleIndex.set(normalizedTitle, nodeId);
                
                // Index words from title
                const words = this.extractWords(title);
                for (const word of words) {
                    if (!this.wordIndex.has(word)) {
                        this.wordIndex.set(word, new Set());
                    }
                    this.wordIndex.get(word).add(nodeId);
                }
            }
            
            // Index scope information
            const scope = entry.scope || {};
            for (const field of ['classHere', 'including', 'notes', 'seeAlso']) {
                if (scope[field]) {
                    const value = scope[field];
                    const items = Array.isArray(value) ? value : [value];
                    for (const item of items) {
                        const words = this.extractWords(String(item));
                        for (const word of words) {
                            if (!this.wordIndex.has(word)) {
                                this.wordIndex.set(word, new Set());
                            }
                            this.wordIndex.get(word).add(nodeId);
                        }
                    }
                }
            }
        }
        
        console.log(`✓ Advanced search index built:`);
        console.log(`  - ${Object.keys(metaData).length} total entries`);
        console.log(`  - ${this.notationIndex.size} notations indexed`);
        console.log(`  - ${this.titleIndex.size} titles indexed`);
        console.log(`  - ${this.wordIndex.size} unique words indexed`);
    }

    // Legacy search method - now uses smart detection
    search(query, maxResults = 50) {
        return this.searchSmart(query, maxResults);
    }

    determineMatchType(nodeId, query, score, searchType = 'keyword') {
        const entry = this.data[nodeId];
        const notation = (entry?.notation || '').toLowerCase();
        const title = this.normalizeText(entry?.pref || '');
        const queryNorm = this.normalizeText(query);
        
        // High precision matches
        if (notation === query.toLowerCase()) {
            return searchType === 'notation' ? 'exact_notation' : 'exact_notation_keyword';
        } else if (title === queryNorm) {
            return searchType === 'keyword' ? 'exact_title' : 'exact_title_notation';
        }
        
        // Score-based classification with search type context
        if (searchType === 'notation') {
            if (score >= 900) {
                return 'notation_high_match';
            } else if (score >= 700) {
                return 'notation_partial_match';
            } else if (score >= 500) {
                return 'notation_contains_match';
            } else {
                return 'notation_weak_match';
            }
        } else { // keyword search
            if (score >= 800) {
                return 'keyword_high_match';
            } else if (score >= 600) {
                return 'keyword_strong_match';
            } else if (score >= 400) {
                return 'keyword_word_match';
            } else if (score >= 200) {
                return 'keyword_partial_match';
            } else {
                return 'keyword_weak_match';
            }
        }
    }

    getSuggestions(partialQuery, maxSuggestions = 10) {
        const suggestions = new Set();
        const partialNorm = this.normalizeText(partialQuery);
        
        // Notation suggestions
        for (const [notation, nodeIds] of this.notationIndex) {
            if (notation.startsWith(partialNorm)) {
                for (const nodeId of nodeIds) {
                    const entry = this.data[nodeId];
                    if (entry?.notation) {
                        suggestions.add(entry.notation);
                    }
                }
            }
        }
        
        // Word suggestions
        const words = this.extractWords(partialQuery);
        if (words.length > 0) {
            const lastWord = words[words.length - 1];
            for (const indexedWord of this.wordIndex.keys()) {
                if (indexedWord.startsWith(lastWord)) {
                    suggestions.add(indexedWord.charAt(0).toUpperCase() + indexedWord.slice(1));
                }
            }
        }
        
        // Built-in synonym suggestions
        for (const [mainTerm, synonyms] of Object.entries(this.synonyms)) {
            if (mainTerm.startsWith(partialNorm)) {
                suggestions.add(mainTerm.charAt(0).toUpperCase() + mainTerm.slice(1));
            }
            for (const synonym of synonyms) {
                if (synonym.startsWith(partialNorm)) {
                    suggestions.add(synonym.charAt(0).toUpperCase() + synonym.slice(1));
                }
            }
        }
        
        return Array.from(suggestions).sort().slice(0, maxSuggestions);
    }

    // Filter results by table (for table-specific searches)
    filterResultsByTable(results, tableFilter) {
        if (!tableFilter) return results;
        
        return results.filter(([nodeId, score, matchType]) => {
            const entry = this.data[nodeId] || {};
            const nodeTable = entry.table || '';
            
            // Handle T3 subtables (T3A, T3B, T3C should all match when filtering for T3)
            if (tableFilter === 'T3') {
                return nodeTable.startsWith('T3');
            }
            
            // For other tables, exact match
            return nodeTable === tableFilter;
        });
    }
}

// Export for use in browsers
if (typeof window !== 'undefined') {
    window.DDCAdvancedSearch = DDCAdvancedSearch;
}