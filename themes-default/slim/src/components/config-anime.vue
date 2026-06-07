<template>
    <div id="config">
        <div id="config-content">
            <form id="configForm" @submit.prevent="save()">
                <vue-tabs>
                    <v-tab key="anidb_settings" title="AnimeDB Settings">
                        <div class="row component-group">
                            <div class="component-group-desc col-xs-12 col-md-2">
                                <span class="icon-notifiers-anime" title="AniDB" />
                                <h3>
                                    <app-link href="http://anidb.info">AniDB</app-link>
                                </h3>
                                <p>AniDB is non-profit database of anime information that is freely open to the public</p>
                            </div>
                            <div class="col-xs-12 col-md-10">

                                <fieldset class="component-group-list">
                                    <config-toggle-slider v-model="anime.anidb.enabled" label="Use AniDB" id="use_anidb">
                                        <span>Should Medusa use data from AniDB?</span>
                                    </config-toggle-slider>

                                    <div v-if="anime.anidb.enabled" id="content_use_anidb">
                                        <config-textbox v-model="anime.anidb.username" label="AniDB Username" id="anidb_username">
                                            <span>Username of your AniDB account</span>
                                        </config-textbox>

                                        <config-textbox v-model="anime.anidb.password" label="AniDB Password" id="anidb_password">
                                            <span>Password of your AniDB account</span>
                                        </config-textbox>

                                        <config-toggle-slider v-model="anime.anidb.useMyList" label="AniDB MyList" id="anidb_use_my_list">
                                            <span>Do you want to add the PostProcessed Episodes to the MyList ?</span>
                                        </config-toggle-slider>

                                    </div><!-- #content_use_anidb //-->
                                </fieldset><!-- .component-group-list //-->
                            </div>
                        </div>
                        <br>
                        <input type="submit"
                               class="btn-medusa config_submitter"
                               value="Save Changes"
                               :disabled="saving"
                        >
                    </v-tab>

                    <v-tab key="myanimelist" title="MyAnimeList">
                        <div class="row component-group">
                            <div class="component-group-desc col-xs-12 col-md-2">
                                <span class="icon-notifiers-anime" title="MyAnimeList" />
                                <h3>
                                    <app-link href="https://myanimelist.net/apiconfig">MyAnimeList</app-link>
                                </h3>
                                <p>Configure the official MyAnimeList API used by anime discovery.</p>
                            </div>
                            <div class="col-xs-12 col-md-10">
                                <fieldset class="component-group-list">
                                    <config-toggle-slider v-model="anime.mal.enabled" label="Use MyAnimeList API" id="use_mal_api">
                                        <span>Use the authenticated official MyAnimeList API when possible. Medusa can fall back to page scraping when this is disabled or not connected.</span>
                                    </config-toggle-slider>

                                    <config-textbox v-model="anime.mal.clientId" label="Client ID" id="mal_client_id">
                                        <span>Client ID from your MyAnimeList API application.</span>
                                    </config-textbox>

                                    <config-textbox v-model="anime.mal.clientSecret" type="password" label="Client Secret" id="mal_client_secret">
                                        <span>Optional for PKCE clients. Stored encrypted in config.ini.</span>
                                    </config-textbox>

                                    <config-template label-for="mal_oauth_status" label="Connection">
                                        <p>
                                            Status:
                                            <strong v-if="malAuth.connected">Connected</strong>
                                            <strong v-else>Not connected</strong>
                                        </p>
                                        <p v-if="malAuth.callbackUrl">Callback URL for your MAL app: <code>{{ malAuth.callbackUrl }}</code></p>
                                        <button
                                            type="button"
                                            class="btn-medusa btn-inline"
                                            :disabled="saving || malAuth.loading || !anime.mal.clientId"
                                            @click.prevent="connectMyAnimeList"
                                        >
                                            Save and Connect MyAnimeList
                                        </button>
                                        <p v-if="!anime.mal.clientId">Enter and save a Client ID before connecting.</p>
                                    </config-template>
                                </fieldset><!-- .component-group-list //-->
                            </div>
                        </div>
                        <br>
                        <input type="submit"
                               class="btn-medusa config_submitter"
                               value="Save Changes"
                               :disabled="saving"
                        >
                    </v-tab>

                    <v-tab key="look_and_feel" title="Look &amp; Feel">
                        <div class="row component-group">
                            <div class="component-group-desc col-xs-12 col-md-2">
                                <span class="icon-notifiers-look" title="look" />
                                <h3><a>Look and Feel</a></h3>
                                <p>How should the anime functions show and behave.</p>
                            </div>
                            <div class="col-xs-12 col-md-10">
                                <fieldset class="component-group-list">
                                    <config-toggle-slider v-model="anime.autoAnimeToList" label="Connect anime to Anime list" id="auto_anime_to_list">
                                        <span>Connect every show marked as anime, to the 'Anime' show list?</span>
                                    </config-toggle-slider>

                                    <config-template v-if="anime.autoAnimeToList" label-for="showlist_default_anime" label="Showlists for Anime">
                                        <multiselect
                                            v-model="animeShowlistDefaultAnime"
                                            :multiple="true"
                                            :options="layout.show.showListOrder"
                                            class="max-input350"
                                        />
                                        <span>Customize the showslist when auto anime lists is enabled</span>
                                    </config-template>

                                    <config-template label-for="preferred_release_groups" label="Preferred Release Groups">
                                        <multiselect
                                            v-model="anime.preferredReleaseGroups"
                                            :multiple="true"
                                            :taggable="true"
                                            :close-on-select="false"
                                            :clear-on-select="false"
                                            :preserve-search="true"
                                            :options="anime.preferredReleaseGroups"
                                            @tag="addPreferredReleaseGroup"
                                            class="max-input350"
                                        />
                                        <span>Priority is top-to-bottom. During anime add, the first matching group is automatically whitelisted.</span>
                                    </config-template>
                                </fieldset><!-- .component-group-list //-->
                            </div>
                        </div><!-- row component-group //-->
                        <br>
                        <input type="submit"
                               class="btn-medusa config_submitter"
                               value="Save Changes"
                               :disabled="saving"
                        >
                    </v-tab>
                </vue-tabs>
            </form><!-- #configForm //-->
        </div><!-- #config-content //-->
    </div><!-- #config //-->
</template>
<script>
import { mapActions, mapState } from 'vuex';
import { AppLink, ConfigTemplate, ConfigTextbox, ConfigToggleSlider } from './helpers';
import { VueTabs, VTab } from 'vue-nav-tabs/dist/vue-tabs.js';
import Multiselect from 'vue-multiselect';
import 'vue-multiselect/dist/vue-multiselect.min.css';

export default {
    name: 'config-anime',
    components: {
        AppLink,
        ConfigTemplate,
        ConfigTextbox,
        ConfigToggleSlider,
        Multiselect,
        VueTabs,
        VTab
    },
    data() {
        return {
            saving: false,
            malAuth: {
                loading: false,
                connected: false,
                callbackUrl: ''
            }
        };
    },
    mounted() {
        this.refreshMalAuthStatus();
        this.handleMalAuthReturn();
    },
    methods: {
        ...mapActions([
            'setConfig',
            'updateShowlistDefault'
        ]),
        async refreshMalAuthStatus() {
            this.malAuth.loading = true;

            try {
                const { data } = await this.client.api.get('auth/myanimelist/status');
                this.malAuth = {
                    loading: false,
                    connected: Boolean(data && data.connected),
                    callbackUrl: data && data.callbackUrl ? data.callbackUrl : ''
                };
                this.anime.mal.connected = this.malAuth.connected;
            } catch (error) {
                this.malAuth = {
                    loading: false,
                    connected: false,
                    callbackUrl: ''
                };
                this.anime.mal.connected = false;
            }
        },
        async connectMyAnimeList() {
            await this.save(false);
            const nextPath = '/config/anime';
            const next = encodeURIComponent(nextPath);
            const webRoot = this.client && this.client.webRoot ? this.client.webRoot : '';
            window.location.assign(`${webRoot}/api/v2/auth/myanimelist/start?next=${next}`);
        },
        handleMalAuthReturn() {
            const query = this.$route.query || {};
            if (query.malAuth !== 'success') {
                return;
            }

            this.$snotify.success('MyAnimeList has been connected successfully.', 'Connected');
            const nextQuery = { ...query };
            delete nextQuery.malAuth;
            this.$router.replace({ query: nextQuery }).catch(() => {});
            this.refreshMalAuthStatus();
        },
        addPreferredReleaseGroup(newTag) {
            const value = (newTag || '').trim();
            if (!value) {
                return;
            }

            const exists = (this.anime.preferredReleaseGroups || [])
                .some(group => String(group).toLowerCase() === value.toLowerCase());

            if (!exists) {
                this.anime.preferredReleaseGroups = [...this.anime.preferredReleaseGroups, value];
            }
        },
        async save(notify = true) {
            const { anime, setConfig } = this;
            const configAnime = {
                ...anime,
                mal: { ...anime.mal }
            };
            delete configAnime.mal.connected;

            // Disable the save button until we're done.
            this.saving = true;
            const section = 'main';

            try {
                await setConfig({ section, config: { anime: configAnime } });
                await this.refreshMalAuthStatus();
                if (notify) {
                    this.$snotify.success(
                        'Saved Anime config',
                        'Saved',
                        { timeout: 5000 }
                    );
                }
            } catch (error) {
                this.$snotify.error(
                    'Error while trying to save anime config',
                    'Error'
                );
                throw error;
            } finally {
                this.saving = false;
            }
        }
    },
    computed: {
        ...mapState({
            anime: state => state.config.anime,
            client: state => state.auth.client,
            layout: state => state.config.layout
        }),
        animeShowlistDefaultAnime: {
            get() {
                const { anime } = this;
                return anime.showlistDefaultAnime;
            },
            set(value) {
                const { anime, updateShowlistDefault } = this;
                updateShowlistDefault(value, anime.showlistDefaultAnime);
            }
        }
    }
};
</script>
<style>
</style>
