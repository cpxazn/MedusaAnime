<template>
    <div id="add-anime">
        <vue-snotify />

        <div class="row controls-row">
            <div class="col-md-6 col-sm-12 controls-column">
                <config-template label-for="anime-source" label="Source">
                    <select id="anime-source" v-model="selectedSource" class="form-control max-input350" @change="loadAnime">
                        <option v-for="option in sourceOptions" :key="option.value" :value="option.value">
                            {{ option.text }}
                        </option>
                    </select>
                </config-template>

                <config-template label-for="anime-year" label="Year">
                    <select id="anime-year" v-model.number="selectedYear" class="form-control max-input350" @change="loadAnime">
                        <option v-for="year in yearOptions" :key="year" :value="year">
                            {{ year }}
                        </option>
                    </select>
                </config-template>

                <config-template label-for="anime-season" label="Season">
                    <select id="anime-season" v-model="selectedSeason" class="form-control max-input350" @change="loadAnime">
                        <option v-for="season in seasonOptions" :key="season.value" :value="season.value">
                            {{ season.text }}
                        </option>
                    </select>
                </config-template>

                <config-template label-for="anime-type" label="Type">
                    <select id="anime-type" v-model="selectedType" class="form-control max-input350">
                        <option v-for="type in typeOptions" :key="type.value" :value="type.value">
                            {{ type.text }}
                        </option>
                    </select>
                </config-template>

                <div class="anime-controls-inline">
                    <button class="btn-medusa btn-inline" @click="goToPreviousSeason">Previous Season</button>
                    <button class="btn-medusa btn-inline" @click="goToNextSeason">Next Season</button>
                    <button class="btn-medusa btn-inline" @click="loadAnime">Refresh</button>
                </div>
            </div>

            <div class="col-md-6 col-sm-12 controls-column controls-column-search">
                <config-template label-for="anime-query" label="Search (Optional)">
                    <input
                        id="anime-query"
                        v-model.trim="searchQuery"
                        type="text"
                        class="form-control max-input350"
                        placeholder="Search title..."
                        @keyup.enter="executeSearch"
                    >
                </config-template>

                <config-template label-for="anime-search-scope" label="Search Scope">
                    <select id="anime-search-scope" v-model="searchScope" class="form-control max-input350">
                        <option value="season">Within Selected Season</option>
                        <option value="global">Global Source Search</option>
                    </select>
                </config-template>

                <div class="anime-controls-inline">
                    <button class="btn-medusa btn-inline" @click="executeSearch">Search</button>
                    <button class="btn-medusa btn-inline" @click="clearSearch">Clear</button>
                </div>

            </div>
        </div>

        <div class="row" v-if="loading">
            <div class="col-md-12 align-center">
                <state-switch state="loading" />
            </div>
        </div>

        <div class="row" v-else-if="filteredAnime.length === 0">
            <div class="col-md-12 align-center no-results">
                No anime found for the selected source/season. Try changing year, season, type, or search query.
            </div>
        </div>

        <div class="row" v-else>
            <div class="col-md-12">
                <div class="anime-grid">
                    <div class="anime-card" v-for="anime in filteredAnime" :key="anime.animeId">
                        <div class="anime-card-image-wrap">
                            <img
                                class="anime-card-image"
                                :src="anime.imageUrl || 'images/poster.png'"
                                :alt="getPrimaryTitle(anime)"
                            >
                        </div>

                        <div class="anime-card-content">
                            <h3 class="anime-card-title">
                                {{ getPrimaryTitle(anime) }}
                            </h3>

                            <div class="anime-card-meta">
                                <span>{{ formatSeasonYear(anime) }}</span>
                                <span>{{ anime.animeType || 'Unknown Type' }}</span>
                            </div>

                            <div class="anime-card-extra" v-if="getAltName(anime)">
                                <strong>Alt Name:</strong> {{ getAltName(anime) }}
                            </div>

                            <div class="anime-card-extra" v-if="anime.genres && anime.genres.length">
                                <strong>Genres:</strong> {{ anime.genres.join(', ') }}
                            </div>

                            <div class="anime-card-extra" v-if="anime.episodeInfo || anime.episodes || anime.episodeDurationMinutes">
                                <strong>Episodes:</strong> {{ formatEpisodeInfo(anime) }}
                            </div>

                            <div class="anime-card-extra" v-if="anime.studios && anime.studios.length">
                                <strong>Studio:</strong> {{ anime.studios.join(', ') }}
                            </div>

                            <div
                                class="anime-card-extra"
                                v-if="anime.nextEpisodeNumber || anime.nextEpisodeRelease || anime.nextEpisodeCountdown"
                            >
                                <strong>Upcoming:</strong>
                                {{ formatUpcoming(anime) }}
                            </div>

                            <p
                                class="anime-card-synopsis"
                            >
                                {{ anime.synopsis || 'No synopsis available.' }}
                            </p>

                            <div class="anime-card-actions">
                                <button class="btn-medusa" @click="openAddNewShow(anime)">Add</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import { mapState } from 'vuex';
import {
    ConfigTemplate,
    StateSwitch
} from './helpers';

const SEASONS = ['WINTER', 'SPRING', 'SUMMER', 'FALL'];

export default {
    name: 'add-anime',
    components: {
        ConfigTemplate,
        StateSwitch
    },
    data() {
        const current = this.currentSeasonAndYear();
        const thisYear = new Date().getFullYear();

        return {
            selectedSource: 'livechart',
            selectedYear: current.year,
            selectedSeason: current.season,
            selectedType: 'TV',
            searchQuery: '',
            searchScope: 'global',
            animeList: [],
            loading: false,
            sourceOptions: [
                { text: 'LiveChart', value: 'livechart' },
                { text: 'MyAnimeList', value: 'myanimelist' }
            ],
            seasonOptions: SEASONS.map(season => ({ text: season, value: season })),
            typeOptions: [
                { text: 'TV (default)', value: 'TV' },
                { text: 'All Types', value: 'ALL' },
                { text: 'Movie', value: 'MOVIE' },
                { text: 'OVA', value: 'OVA' },
                { text: 'ONA', value: 'ONA' }
            ],
            yearOptions: Array.from({ length: 8 }, (_, index) => thisYear - 1 + index)
        };
    },
    computed: {
        ...mapState({
            client: state => state.auth.client,
            general: state => state.config.general,
            statuses: state => state.config.consts.statuses
        }),
        filteredAnime() {
            const baseList = this.searchScope === 'season' && this.searchQuery
                ? this.animeList.filter(anime => this.matchesSearchQuery(anime, this.searchQuery))
                : this.animeList;

            if (this.selectedType === 'ALL') {
                return baseList;
            }

            const target = this.selectedType.toUpperCase();
            return baseList.filter(anime => {
                const animeType = (anime.animeType || '').toUpperCase();
                return animeType.indexOf(target) !== -1;
            });
        },
        wantedStatusValue() {
            const wantedStatus = this.statuses.find(status => (status.key || '').toLowerCase() === 'wanted');
            return wantedStatus ? wantedStatus.value : this.general.showDefaults.status;
        }
    },
    mounted() {
        this.loadAnime();
    },
    methods: {
        executeSearch() {
            this.loadAnime();
        },
        clearSearch() {
            this.searchQuery = '';
            this.loadAnime();
        },
        currentSeasonAndYear() {
            const now = new Date();
            const month = now.getMonth() + 1;

            if (month <= 3) {
                return { season: 'WINTER', year: now.getFullYear() };
            }
            if (month <= 6) {
                return { season: 'SPRING', year: now.getFullYear() };
            }
            if (month <= 9) {
                return { season: 'SUMMER', year: now.getFullYear() };
            }
            return { season: 'FALL', year: now.getFullYear() };
        },
        async loadAnime() {
            this.loading = true;

            try {
                const params = {
                    source: this.selectedSource,
                    year: this.selectedYear,
                    season: this.selectedSeason,
                    limit: 200
                };

                let response;
                if (this.searchQuery && this.searchScope === 'global') {
                    params.q = this.searchQuery;
                    response = await this.client.api.get('anime/search', { params });
                } else {
                    response = await this.client.api.get('anime/seasonal', { params });
                }

                this.animeList = Array.isArray(response.data) ? response.data : [];
            } catch (error) {
                this.animeList = [];
                this.$snotify.error(
                    'Could not load anime list from the selected source.',
                    'Error'
                );
            } finally {
                this.loading = false;
            }
        },
        goToPreviousSeason() {
            const currentIndex = SEASONS.indexOf(this.selectedSeason);
            if (currentIndex <= 0) {
                this.selectedSeason = SEASONS[SEASONS.length - 1];
                this.selectedYear -= 1;
            } else {
                this.selectedSeason = SEASONS[currentIndex - 1];
            }

            this.loadAnime();
        },
        goToNextSeason() {
            const currentIndex = SEASONS.indexOf(this.selectedSeason);
            if (currentIndex === SEASONS.length - 1) {
                this.selectedSeason = SEASONS[0];
                this.selectedYear += 1;
            } else {
                this.selectedSeason = SEASONS[currentIndex + 1];
            }

            this.loadAnime();
        },
        formatEpisodeInfo(anime) {
            if (anime.episodeInfo) {
                return anime.episodeInfo;
            }

            const ep = anime.episodes ? `${anime.episodes} eps` : '? eps';
            const mins = anime.episodeDurationMinutes ? `${anime.episodeDurationMinutes}m` : '?m';
            return `${ep} × ${mins}`;
        },
        formatUpcoming(anime) {
            const parts = [];

            if (anime.nextEpisodeNumber) {
                parts.push(`EP${anime.nextEpisodeNumber}`);
            }
            if (anime.nextEpisodeRelease) {
                parts.push(anime.nextEpisodeRelease);
            }
            if (anime.nextEpisodeCountdown) {
                parts.push(`(${anime.nextEpisodeCountdown})`);
            }

            return parts.join(' • ') || 'N/A';
        },
        formatSeasonYear(anime) {
            if (anime.season || anime.year) {
                const season = anime.season || 'Unknown Season';
                const year = anime.year || 'Unknown Year';
                return `${season} ${year}`.trim();
            }

            return 'Season info unavailable';
        },
        normalizeSearchText(value) {
            return String(value || '')
                .trim()
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, ' ')
                .replace(/\s+/g, ' ')
                .trim();
        },
        matchesSearchQuery(anime, query) {
            const needle = this.normalizeSearchText(query);
            if (!needle) {
                return true;
            }

            const fields = [
                anime.titleRomanji,
                anime.titleEnglish,
                anime.titleJapanese,
                anime.displayTitle
            ];

            return fields.some(field => {
                const haystack = this.normalizeSearchText(field);
                return haystack && haystack.indexOf(needle) !== -1;
            });
        },
        getPrimaryTitle(anime) {
            return anime.titleRomanji || anime.titleEnglish || anime.titleJapanese || anime.displayTitle;
        },
        getAltName(anime) {
            const primary = this.getPrimaryTitle(anime);
            const alternate = anime.titleRomanji ? anime.titleEnglish : anime.titleRomanji;

            if (!primary || !alternate) {
                return null;
            }

            if (String(primary).trim().toLowerCase() === String(alternate).trim().toLowerCase()) {
                return null;
            }

            return alternate;
        },
        getIndexerQueryTitle(anime) {
            const preferred = anime.titleEnglish || anime.titleRomanji || anime.titleJapanese || anime.displayTitle;
            return this.stripSeasonSuffix(preferred);
        },
        stripSeasonSuffix(title) {
            if (!title) {
                return title;
            }

            let cleaned = String(title).trim();

            // Strip explicit sequel markers that can hurt indexer matching.
            cleaned = cleaned
                .replace(/\s+season\s+\d+\s*$/i, '')
                .replace(/\s+cour\s+\d+\s*$/i, '')
                .replace(/\s+part\s+\d+\s*$/i, '')
                .replace(/\s+pt\.?\s*\d+\s*$/i, '');

            // Strip trailing sequel numbers, including attached numbers like "Rotten2".
            cleaned = cleaned
                .replace(/([A-Za-z])\d+\s*$/, '$1')
                .replace(/\s+\d+\s*$/, '');

            return cleaned.trim() || String(title).trim();
        },
        resolveAnimeRootDir() {
            const rawRootDirs = this.general.rootDirs || [];
            if (rawRootDirs.length < 2) {
                return '';
            }

            const paths = rawRootDirs.slice(1);
            const animeRoot = paths.find(path => /anime/i.test(path));
            if (animeRoot) {
                return animeRoot;
            }

            const defaultIndex = Number.parseInt(rawRootDirs[0], 10);
            if (Number.isInteger(defaultIndex) && paths[defaultIndex]) {
                return paths[defaultIndex];
            }

            return paths[0] || '';
        },
        joinPath(rootDir, folderName) {
            if (!rootDir) {
                return '';
            }

            const separator = rootDir.indexOf('\\') !== -1 ? '\\' : '/';
            const base = rootDir.replace(/[\\/]$/, '');
            return folderName ? `${base}${separator}${folderName}` : base;
        },
        async enrichAnimeMetadata(anime) {
            let enriched = { ...anime };

            try {
                const { data } = await this.client.api.get('anime/details', {
                    params: {
                        id: anime.animeId,
                        source: this.selectedSource
                    },
                    timeout: 30000
                });

                if (data && typeof data === 'object') {
                    enriched = { ...enriched, ...data };
                }
            } catch (error) {
                // Best-effort enrichment only.
            }

            // LiveChart can miss AniDB cross refs; fall back via MAL lookup by title.
            if (!enriched.anidbId && this.selectedSource === 'livechart') {
                const query = this.getPrimaryTitle(enriched) || this.getPrimaryTitle(anime);
                if (query) {
                    try {
                        const { data: malSearchData } = await this.client.api.get('anime/search', {
                            params: {
                                source: 'myanimelist',
                                q: query,
                                limit: 5
                            },
                            timeout: 30000
                        });

                        const malCandidates = Array.isArray(malSearchData) ? malSearchData : [];
                        const normalize = value => String(value || '').trim().toLowerCase();
                        const targetNames = [
                            enriched.titleEnglish,
                            enriched.titleRomanji,
                            enriched.titleJapanese,
                            enriched.displayTitle,
                            query
                        ].map(normalize).filter(Boolean);

                        const selectedMal = malCandidates.find(candidate => {
                            const names = [
                                candidate.titleEnglish,
                                candidate.titleRomanji,
                                candidate.titleJapanese,
                                candidate.displayTitle
                            ].map(normalize).filter(Boolean);
                            return names.some(name => targetNames.includes(name));
                        }) || malCandidates[0];

                        if (selectedMal && selectedMal.animeId) {
                            const { data: malDetails } = await this.client.api.get('anime/details', {
                                params: {
                                    id: selectedMal.animeId,
                                    source: 'myanimelist'
                                },
                                timeout: 30000
                            });

                            if (malDetails && malDetails.anidbId) {
                                enriched.anidbId = malDetails.anidbId;
                            }
                        }
                    } catch (error) {
                        // Best-effort enrichment only.
                    }
                }
            }

            return enriched;
        },
        openAddNewShow(anime) {
            // Use the list-item data directly — no blocking enrichment fetch needed.
            // Titles come from the seasonal list (data-romaji attr, etc.), which are already
            // correct after the server-side JSON-LD fix. The anidbId may be null here, but
            // fetch_releasegroups on the backend has a MAL-based fallback for that case.
            const animeTitle = this.getPrimaryTitle(anime);
            const indexerQueryTitle = this.getIndexerQueryTitle(anime);
            const romanjiTitle = this.stripSeasonSuffix(anime.titleRomanji || '');
            const animeRootDir = this.resolveAnimeRootDir();
            const showDir = this.joinPath(animeRootDir, anime.directoryName || animeTitle);

            const providedInfo = {
                // Prefill mode only: still require selecting an indexer result in step 1.
                // Using `use: true` without a valid showId/indexerId hides search and breaks add.
                use: false,
                showName: indexerQueryTitle,
                releaseGroupRomanji: romanjiTitle,
                releaseGroupAnidbId: anime.anidbId || null,
                indexerId: 0,
                indexerLanguage: this.general.indexerDefaultLanguage,
                showDir,
                unattended: false
            };

            const presetShowOptions = {
                use: true,
                subtitles: this.general.showDefaults.subtitles,
                status: this.wantedStatusValue,
                statusAfter: this.general.showDefaults.statusAfter,
                seasonFolders: true,
                anime: true,
                scene: this.general.showDefaults.scene,
                showLists: this.general.showDefaults.showLists,
                release: {
                    whitelist: [],
                    blacklist: []
                },
                quality: this.general.showDefaults.quality
            };

            this.$router.push({
                name: 'addNewShow',
                params: {
                    providedInfo,
                    presetShowOptions
                }
            });
        }
    }
};
</script>

<style scoped>
.controls-row {
    margin-bottom: 20px;
}

.controls-column {
    margin-bottom: 12px;
}

.controls-column-search {
    padding-top: 2px;
}

.anime-controls-inline {
    display: inline-block;
    margin: 10px 12px 10px 0;
    vertical-align: bottom;
}

.btn-inline {
    margin-right: 6px;
}

.no-results {
    margin-top: 15px;
}

.anime-grid {
    display: grid;
    grid-gap: 16px;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}

.anime-card {
    border: 1px solid #d0d0d0;
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: #fff;
}

.anime-card-image-wrap {
    background: #f2f2f2;
    display: flex;
    justify-content: center;
    max-height: 360px;
    overflow: hidden;
}

.anime-card-image {
    display: block;
    height: auto;
    width: 100%;
}

.anime-card-content {
    color: #1f1f1f;
    display: flex;
    flex: 1;
    flex-direction: column;
    padding: 12px;
}

.anime-card-title {
    color: #1f1f1f;
    font-size: 16px;
    margin: 0 0 8px;
}

.anime-card-meta {
    color: #555;
    display: flex;
    font-size: 12px;
    gap: 10px;
    margin-bottom: 8px;
}

.anime-card-synopsis {
    color: #2f2f2f;
    max-height: 8.5em;
    margin: 0 0 8px;
    overflow-y: auto;
    padding-right: 4px;
    white-space: pre-line;
}

.anime-card-extra {
    color: #404040;
    font-size: 12px;
    line-height: 1.4;
    margin: 0 0 6px;
}

.anime-card-actions {
    margin-top: auto;
    padding-top: 10px;
}
</style>
